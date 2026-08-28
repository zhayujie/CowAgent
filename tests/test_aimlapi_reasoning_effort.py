# encoding:utf-8
"""
Regression coverage for a live-testing bug: AI/ML API's own request
validator only accepts reasoning_effort in {"low", "medium", "high"} and
400s on "none" *before* the request reaches the model — but
OpenAICompatibleBot.call_with_tools() used to force reasoning_effort to
the literal string "none" whenever a GPT-5.x/o-series reasoning model was
called with tools, to work around a real-OpenAI-specific restriction.
Verified live against https://api.aimlapi.com/v1/chat/completions:
- reasoning_effort="none" -> 400 invalid_enum_value (AI/ML API's own gateway)
- reasoning_effort="low"/"medium"/"high" + tools -> 400 from the underlying
  model itself ("Function tools with reasoning_effort are not supported...")
- reasoning_effort omitted entirely + tools -> succeeds, including an actual
  tool_calls response.

The fix: omit reasoning_effort entirely for gpt5-reasoning models with
tools, rather than forcing "none". This test locks that in.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _call_and_capture(monkeypatch, model_name, tools):
    from config import conf
    from models.aimlapi.aimlapi_bot import AimlapiBot

    captured = {}
    bot = AimlapiBot.__new__(AimlapiBot)

    monkeypatch.setitem(conf(), "model", model_name)
    monkeypatch.setitem(conf(), "aimlapi_api_key", "test-key")
    monkeypatch.setattr(
        bot,
        "_handle_sync_response",
        lambda request_params, api_key, api_base: captured.setdefault("body", request_params),
    )

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=tools,
        stream=False,
        model=model_name,
    )
    return captured["body"]


def test_gpt5_with_tools_omits_reasoning_effort(monkeypatch):
    """Was forced to "none" before the fix - AI/ML API's validator rejects
    that value outright, so every gpt-5.x agent-mode tool call 400'd."""
    tools = [{
        "name": "get_time",
        "description": "get current time",
        "input_schema": {"type": "object", "properties": {}},
    }]
    body = _call_and_capture(monkeypatch, "openai/gpt-5-5", tools)

    assert body["tools"]
    assert "reasoning_effort" not in body


def test_gpt5_without_tools_still_omits_reasoning_effort(monkeypatch):
    body = _call_and_capture(monkeypatch, "openai/gpt-5-5", tools=[])

    assert "tools" not in body
    assert "reasoning_effort" not in body


def test_non_reasoning_model_with_tools_is_unaffected(monkeypatch):
    """Sanity check: the gpt5-reasoning branch must not touch other models."""
    tools = [{
        "name": "get_time",
        "description": "get current time",
        "input_schema": {"type": "object", "properties": {}},
    }]
    body = _call_and_capture(monkeypatch, "deepseek/deepseek-v4-pro-0813", tools)

    assert body["tools"]
    assert "reasoning_effort" not in body
    # Non-reasoning models keep their sampling params.
    assert "temperature" in body
