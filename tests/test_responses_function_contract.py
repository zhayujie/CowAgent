"""Responses uses flat function definitions and flat forced-function choices."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from models.openai import responses_adapter as adapter
from models.openai_compatible_bot import OpenAICompatibleBot


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("nested", [True, False])
def test_function_strictness_is_preserved(strict, nested):
    fn = {"name": "read", "parameters": {"type": "object"}, "strict": strict}
    tool = {"type": "function", "function": fn} if nested else {"type": "function", **fn}
    original = deepcopy(tool)
    converted = adapter.tools_to_responses([tool])[0]
    assert converted["strict"] is strict
    assert tool == original


def test_forced_function_choice_is_flattened_without_mutating_input():
    choice = {"type": "function", "function": {"name": "read"}}
    payload = adapter.build_responses_payload(model="test", messages=[], tools=[{"name": "read"}], tool_choice=choice)
    assert payload["tool_choice"] == {"type": "function", "name": "read"}
    assert choice == {"type": "function", "function": {"name": "read"}}


@pytest.mark.parametrize("choice", ["auto", "required", "none", {"type": "function", "name": "read"}])
def test_existing_responses_choices_are_preserved(choice):
    payload = adapter.build_responses_payload(model="test", messages=[], tools=[{"name": "read"}], tool_choice=choice)
    assert payload["tool_choice"] == choice


class Bot(OpenAICompatibleBot):
    def get_api_config(self):
        return {"model": "test", "api_type": "responses", "api_base": "https://test.invalid/v1"}


def test_native_bot_http_request_preserves_function_contract(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"status": "completed", "output": []}
    request = Mock(return_value=response)
    monkeypatch.setattr("models.openai.openai_http_client.requests.post", request)
    Bot().call_with_tools(
        [{"role": "user", "content": "read"}],
        tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}, "strict": False}}],
        tool_choice={"type": "function", "function": {"name": "read"}},
    )
    payload = request.call_args.kwargs["json"]
    assert payload["tool_choice"] == {"type": "function", "name": "read"}
    assert payload["tools"][0]["strict"] is False


@pytest.mark.parametrize("nested", [True, False])
def test_unset_strictness_is_sent_as_non_strict(nested):
    # Responses compiles a function with no ``strict`` in strict mode, so an MCP
    # schema using e.g. ``dependentRequired`` would fail the whole request.
    params = {
        "type": "object",
        "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
        "dependentRequired": {"start": ["end"]},
    }
    fn = {"name": "list_events", "parameters": params}
    tool = {"type": "function", "function": fn} if nested else {"type": "function", **fn}
    original = deepcopy(tool)
    converted = adapter.tools_to_responses([tool])[0]
    assert converted["strict"] is False
    assert converted["parameters"] == params
    assert tool == original
