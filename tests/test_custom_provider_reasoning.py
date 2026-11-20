# encoding:utf-8
"""A custom provider may declare its reasoning control per model.

A gateway fronts models from many vendors, and each one takes a different
parameter (or none at all). The model catalog carries that declaration, and
CowAgent then sends exactly the declared parameter — never a guessed one,
because several vendors reject an unknown field outright.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import model_catalog
from models.openai import openai_http_client
from models.openai_compatible_bot import OpenAICompatibleBot
from models.reasoning_capabilities import get_reasoning_capability

CUSTOM = "custom:abc12345"
EFFORT_DECL = {"param": "reasoning_effort", "options": ["minimal", "low"], "default": "minimal"}
THINKING_DECL = {"param": "thinking", "options": ["enabled", "disabled"], "default": "disabled"}


@pytest.fixture
def store(monkeypatch, tmp_path):
    path = tmp_path / "models.json"
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(path))
    model_catalog._invalidate()
    yield path
    model_catalog._invalidate()


class _Bot(OpenAICompatibleBot):
    def __init__(self, bot_type=None):
        self._bot_type = bot_type or CUSTOM

    def get_api_config(self):
        return {"model": "gateway-model", "api_key": "sk-cust",
                "api_base": "https://gateway.example/v1"}


def _post_body(bot, **kwargs):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "model": "gateway-model",
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    with patch.object(openai_http_client.requests, "post", return_value=response) as post:
        bot.call_with_tools([{"role": "user", "content": "hi"}], tools=None,
                            stream=False, **kwargs)
    return post.call_args.kwargs["json"]


# --- catalog storage -------------------------------------------------------

def test_custom_provider_keeps_the_reasoning_declaration(store):
    model_catalog.save_catalog(CUSTOM, [
        {"name": "vendor-fast", "reasoning": EFFORT_DECL},
        {"name": "vendor-plain"},
    ])

    entries = model_catalog.get_catalog(CUSTOM)
    assert entries[0]["reasoning"] == {
        "param": "reasoning_effort", "options": ["minimal", "low"],
        "default": "minimal", "thinking_only": True}
    assert "reasoning" not in entries[1]


def test_thinking_declaration_is_not_thinking_only(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "vendor", "reasoning": THINKING_DECL}])

    assert model_catalog.get_catalog(CUSTOM)[0]["reasoning"]["thinking_only"] is False


def test_default_falls_back_to_the_first_option(store):
    model_catalog.save_catalog(CUSTOM, [
        {"name": "vendor", "reasoning": {"param": "reasoning_effort", "options": ["low", "high"]}},
    ])

    assert model_catalog.get_catalog(CUSTOM)[0]["reasoning"]["default"] == "low"


@pytest.mark.parametrize("declaration", [
    {"param": "temperature", "options": ["low"]},      # unknown parameter
    {"param": "reasoning_effort", "options": []},      # nothing to choose from
    {"param": "reasoning_effort", "options": ["low"], "default": "high"},  # default not offered
    {"param": "reasoning_effort", "options": 123},      # options must be a list
    "reasoning_effort",                                # must be an object
])
def test_malformed_declarations_are_rejected(store, declaration):
    with pytest.raises(ValueError):
        model_catalog.save_catalog(CUSTOM, [{"name": "vendor", "reasoning": declaration}])


def test_a_single_option_may_be_written_as_a_string(store):
    model_catalog.save_catalog(CUSTOM, [
        {"name": "vendor", "reasoning": {"param": "reasoning_effort", "options": "minimal"}}])

    assert model_catalog.get_catalog(CUSTOM)[0]["reasoning"]["options"] == ["minimal"]


def test_builtin_vendor_does_not_store_a_declaration(store):
    model_catalog.save_catalog("deepseek", [
        {"name": "deepseek-flash", "reasoning": EFFORT_DECL}])

    assert model_catalog.get_catalog("deepseek") == [
        {"name": "deepseek-flash", "capabilities": ["text"]}]


# --- capability ------------------------------------------------------------

def test_declared_model_exposes_its_capability(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "vendor-fast", "reasoning": EFFORT_DECL}])

    cap = get_reasoning_capability(CUSTOM, "vendor-fast")
    assert cap["supported"] is True
    assert cap["param"] == "reasoning_effort"
    assert cap["default"] == "minimal"
    assert [o["value"] for o in cap["options"]] == ["minimal", "low"]
    assert cap["thinking_only"] is True


def test_model_without_a_declaration_has_no_reasoning_control(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "vendor-plain"}])

    assert get_reasoning_capability(CUSTOM, "vendor-plain") == {"supported": False, "options": []}


def test_builtin_capabilities_are_unchanged():
    cap = get_reasoning_capability("deepseek", "deepseek-v4-flash")
    assert cap["supported"] is True
    assert cap["param"] == "reasoning_effort"


# --- what actually goes on the wire ----------------------------------------

def test_declared_effort_is_sent(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "vendor-fast", "reasoning": EFFORT_DECL}])

    body = _post_body(_Bot(), model="vendor-fast", reasoning_effort="minimal")

    assert body["reasoning_effort"] == "minimal"


def test_effort_outside_the_declared_values_is_not_sent(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "vendor-fast", "reasoning": EFFORT_DECL}])

    body = _post_body(_Bot(), model="vendor-fast", reasoning_effort="max")

    assert "reasoning_effort" not in body


def test_thinking_switch_is_sent_as_declared(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "vendor", "reasoning": THINKING_DECL}])

    body = _post_body(_Bot(), model="vendor", thinking={"type": "disabled"})

    assert body["thinking"] == {"type": "disabled"}


def test_undeclared_model_gets_no_reasoning_parameter(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "vendor-plain"}])

    body = _post_body(_Bot(), model="vendor-plain", reasoning_effort="minimal",
                      thinking={"type": "disabled"})

    assert "reasoning_effort" not in body
    assert "thinking" not in body


def test_builtin_provider_is_never_touched_by_the_declaration():
    # A built-in vendor's protocol comes from the code, not the catalog.
    body = _post_body(_Bot(bot_type="chatGPT"), model="gpt-4o", reasoning_effort="minimal")

    assert "reasoning_effort" not in body
