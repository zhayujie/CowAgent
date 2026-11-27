"""The non-streaming ModelScope path must return the tool calls it received.

`reply_text` is the only non-streaming request builder, and it returned just
`total_tokens` / `completion_tokens` / `content`. `_handle_sync_response` then
looked for `result["tool_calls"]`, a key nothing ever set -- so its whole
`if tool_calls:` branch was dead -- and stamped `finish_reason: "stop"` on every
reply. A turn where the model asked for a tool came back as "finished, no text,
no calls", so the tool never ran and the agent stopped with an empty answer.
"""
import json

from config import conf
from models.modelscope import modelscope_bot

TOOL_CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "read_file", "arguments": "{}"},
}


class _Response:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _request(monkeypatch, payload, status_code=200):
    monkeypatch.setitem(conf(), "modelscope_api_key", "k")
    monkeypatch.setitem(conf(), "modelscope_base_url", "https://example.test/v1")
    bot = modelscope_bot.ModelScopeBot()
    monkeypatch.setattr(modelscope_bot.requests, "post",
                        lambda *a, **k: _Response(payload, status_code))
    return bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[{"name": "read_file", "description": "d", "input_schema": {}}],
        stream=False,
    )


def _tool_call_payload(finish_reason="tool_calls"):
    return {
        "choices": [{
            "message": {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]},
            "finish_reason": finish_reason,
        }],
        "usage": {"total_tokens": 7, "completion_tokens": 3},
    }


def test_a_tool_call_survives_the_sync_path(monkeypatch):
    out = _request(monkeypatch, _tool_call_payload())

    calls = out["choices"][0]["message"]["tool_calls"]
    assert calls == [TOOL_CALL], f"the tool call was dropped: {calls!r}"


def test_a_tool_call_turn_reports_tool_calls(monkeypatch):
    out = _request(monkeypatch, _tool_call_payload())

    assert out["choices"][0]["finish_reason"] == "tool_calls"


def test_a_truncated_answer_reports_length(monkeypatch):
    """`length` is the only signal that the answer was cut off at the cap."""
    payload = _tool_call_payload("length")
    payload["choices"][0]["message"] = {"role": "assistant", "content": "half a sen"}

    out = _request(monkeypatch, payload)

    assert out["choices"][0]["finish_reason"] == "length"


def test_a_plain_answer_is_still_stop(monkeypatch):
    """Control: nothing about the ordinary turn changes."""
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "hello"},
                     "finish_reason": "stop"}],
        "usage": {"total_tokens": 5, "completion_tokens": 1},
    }

    out = _request(monkeypatch, payload)

    assert out["choices"][0]["message"] == {
        "role": "assistant", "content": "hello", "tool_calls": None,
    }
    assert out["choices"][0]["finish_reason"] == "stop"


def test_an_answer_without_a_finish_reason_still_reads_as_stop(monkeypatch):
    """Control: a provider that omits the field must not break the loop."""
    payload = {"choices": [{"message": {"role": "assistant", "content": "hello"}}],
               "usage": {}}

    out = _request(monkeypatch, payload)

    assert out["choices"][0]["finish_reason"] == "stop"


def test_a_rejected_request_keeps_its_error_text(monkeypatch):
    """Control: the error branch still flows through as before."""
    payload = {"error": {"message": "Invalid token", "type": "auth"}}

    out = _request(monkeypatch, payload, status_code=401)

    assert out["choices"][0]["message"]["content"] == "授权失败，请检查 API Key 是否正确"
    assert out["choices"][0]["finish_reason"] == "stop"
