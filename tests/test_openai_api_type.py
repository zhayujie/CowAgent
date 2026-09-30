# encoding:utf-8
"""Routing between /chat/completions and /responses via ``open_ai_api_type``."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module
from config import Config
from models.openai import responses_adapter


class _FakeClient:
    def __init__(self):
        self.calls = []

    def chat_completions(self, **kwargs):
        self.calls.append(("chat", kwargs))
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def responses(self, **kwargs):
        self.calls.append(("responses", kwargs))
        return {
            "id": "resp_1",
            "model": kwargs.get("model"),
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


def _make_bot(monkeypatch, api_type=None, bot_type="chatGPT", model="gpt-5.5"):
    cfg = {
        "bot_type": bot_type,
        "model": model,
        "open_ai_api_key": "sk-test",
        "open_ai_api_base": "https://relay.example.com/v1",
        "custom_providers": [{"id": "c1", "name": "c", "api_key": "k",
                              "api_base": "https://custom.example.com/v1", "model": model}],
    }
    if api_type is not None:
        cfg["open_ai_api_type"] = api_type
    monkeypatch.setattr(config_module, "config", Config(cfg))

    from models.chatgpt.chat_gpt_bot import ChatGPTBot
    bot = ChatGPTBot(bot_type)
    client = _FakeClient()
    bot._http_client = client
    return bot, client


def _call_tools(bot, model="gpt-5.5", **kwargs):
    tools = [{"name": "read", "description": "read a file",
              "input_schema": {"type": "object", "properties": {}}}]
    return bot.call_with_tools(
        [{"role": "user", "content": "hi"}], tools=tools, stream=False, model=model, **kwargs,
    )


def test_default_keeps_chat_completions_for_gpt5(monkeypatch):
    bot, client = _make_bot(monkeypatch)
    _call_tools(bot)
    kind, params = client.calls[0]
    assert kind == "chat"
    assert params["reasoning_effort"] == "none"


def test_responses_mode_routes_gpt5_to_responses_without_thinking(monkeypatch):
    bot, client = _make_bot(monkeypatch, api_type="responses")
    result = _call_tools(bot, thinking={"type": "disabled"})
    kind, params = client.calls[0]
    assert kind == "responses"
    assert params["reasoning"] == {"effort": "none"}
    assert "temperature" not in params
    assert params["tools"][0]["name"] == "read"
    assert result["choices"][0]["message"]["content"] == "ok"


def test_responses_mode_thinking_enabled_uses_model_default_effort(monkeypatch):
    bot, client = _make_bot(monkeypatch, api_type="responses")
    _call_tools(bot, thinking={"type": "enabled"})
    _, params = client.calls[0]
    assert "reasoning" not in params


def test_responses_mode_thinking_enabled_forwards_configured_effort(monkeypatch):
    bot, client = _make_bot(monkeypatch, api_type="responses")
    _call_tools(bot, thinking={"type": "enabled"}, reasoning_effort="high")
    _, params = client.calls[0]
    assert params["reasoning"] == {"effort": "high"}


def test_responses_mode_non_reasoning_model_sends_no_effort(monkeypatch):
    bot, client = _make_bot(monkeypatch, api_type="responses", model="gpt-4.1")
    _call_tools(bot, model="gpt-4.1", thinking={"type": "disabled"})
    kind, params = client.calls[0]
    assert kind == "responses"
    assert "reasoning" not in params


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol"])
def test_auto_mode_gpt6_behavior_unchanged(monkeypatch, model):
    bot, client = _make_bot(monkeypatch, model=model)
    _call_tools(bot, model=model, thinking={"type": "disabled"})
    kind, params = client.calls[0]
    assert kind == "responses"
    assert "reasoning" not in params


def test_chat_mode_forces_chat_completions(monkeypatch):
    bot, client = _make_bot(monkeypatch, api_type="chat", model="gpt-6-astra")
    _call_tools(bot, model="gpt-6-astra")
    assert client.calls[0][0] == "chat"


def test_custom_provider_ignores_openai_api_type(monkeypatch):
    bot, client = _make_bot(monkeypatch, api_type="responses", bot_type="custom:c1")
    _call_tools(bot)
    assert client.calls[0][0] == "chat"


def test_reply_text_uses_responses_when_configured(monkeypatch):
    from models.session_manager import Session

    bot, client = _make_bot(monkeypatch, api_type="responses")
    session = Session("s1", system_prompt="")
    session.messages = [{"role": "user", "content": "title please"}]
    result = bot.reply_text(session)
    kind, params = client.calls[0]
    assert kind == "responses"
    assert params["model"] == "gpt-5.5"
    assert params["reasoning"] == {"effort": "none"}
    assert result["content"] == "ok"
    assert result["completion_tokens"] == 1


def test_reply_text_default_keeps_chat_completions(monkeypatch):
    from models.session_manager import Session

    bot, client = _make_bot(monkeypatch)
    session = Session("s1", system_prompt="")
    session.messages = [{"role": "user", "content": "title please"}]
    bot.reply_text(session)
    assert client.calls[0][0] == "chat"


def test_azure_ignores_openai_api_type():
    from models.chatgpt.chat_gpt_bot import AzureChatGPTBot

    bot = AzureChatGPTBot.__new__(AzureChatGPTBot)
    assert bot._openai_api_type() == responses_adapter.API_TYPE_AUTO


@pytest.mark.parametrize("value, expected", [
    (None, "auto"), ("", "auto"), ("RESPONSES", "responses"),
    ("chat", "chat"), ("bogus", "auto"),
])
def test_resolve_api_type(value, expected):
    assert responses_adapter.resolve_api_type(value) == expected


def test_normalize_effort_only_clamps_responses_only_models():
    assert responses_adapter.normalize_effort("none", "gpt-5.5") == "none"
    assert responses_adapter.normalize_effort("none", "gpt-6-astra") == "low"
    assert responses_adapter.normalize_effort("none", "gpt-6.1-sol") == "low"
    assert responses_adapter.normalize_effort("minimal") == "low"
