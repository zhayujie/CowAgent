"""Gemini's functionResponse.response is a JSON object (Struct).

Tool results arrive as text; MCP tools in particular return whatever the
server printed, which is often a JSON array or a bare number. Those must be
wrapped in an object, or Gemini rejects the whole request.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}


def _function_responses(monkeypatch, tool_content):
    from config import conf
    from models.gemini import google_gemini_bot
    from models.gemini.google_gemini_bot import GoogleGeminiBot

    monkeypatch.setitem(conf(), "gemini_api_key", "test")
    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr(google_gemini_bot.requests, "post", fake_post)
    bot = GoogleGeminiBot.__new__(GoogleGeminiBot)
    messages = [
        {"role": "user", "content": "list my issues"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "call_1", "name": "list_issues", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": tool_content},
        ]},
    ]
    bot.call_with_tools(messages, tools=[], stream=False, model="gemini-2.5-flash")
    return [
        part["functionResponse"]
        for content in captured["payload"]["contents"]
        for part in content["parts"]
        if "functionResponse" in part
    ]


def test_json_array_tool_result_is_wrapped_in_an_object(monkeypatch):
    (fr,) = _function_responses(monkeypatch, '[{"number": 1}, {"number": 2}]')
    assert fr["name"] == "list_issues"
    assert fr["response"] == {"result": [{"number": 1}, {"number": 2}]}


def test_scalar_tool_result_is_wrapped_in_an_object(monkeypatch):
    (fr,) = _function_responses(monkeypatch, "42")
    assert fr["response"] == {"result": 42}


def test_object_tool_result_is_passed_through(monkeypatch):
    (fr,) = _function_responses(monkeypatch, '{"output": "done"}')
    assert fr["response"] == {"output": "done"}
