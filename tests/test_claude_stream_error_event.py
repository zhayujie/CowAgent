# encoding:utf-8
"""Anthropic can fail a stream with an ``error`` SSE event after HTTP 200.

The bot must surface it as an error chunk; ignoring it ends the stream with
no tool call and a truncated (or empty) reply that the agent treats as final.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeStreamResponse:
    status_code = 200
    text = ""

    def __init__(self, events):
        self._lines = [f"data: {json.dumps(e)}".encode() for e in events]

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        pass


def _stream(monkeypatch, events):
    from config import conf
    from models.claudeapi import claude_api_bot
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    monkeypatch.setitem(conf(), "claude_api_key", "test")
    monkeypatch.setitem(conf(), "proxy", "")
    monkeypatch.setattr(claude_api_bot.requests, "post",
                        lambda *a, **kw: _FakeStreamResponse(events))
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    return list(bot._handle_stream_response({"model": "claude-sonnet-4-6", "messages": []}))


def test_mid_stream_overloaded_error_is_surfaced(monkeypatch):
    chunks = _stream(monkeypatch, [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Let me"}},
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    ])

    errors = [c for c in chunks if c.get("error")]
    assert len(errors) == 1
    assert errors[0]["status_code"] == 529
    # The agent retries/falls back on errors whose text mentions "overloaded".
    assert "overloaded" in errors[0]["message"].lower()
    assert chunks[-1] is errors[0]


def test_error_event_during_tool_use_is_not_dropped(monkeypatch):
    chunks = _stream(monkeypatch, [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": "{\"path\": "}},
        {"type": "error", "error": {"type": "api_error", "message": "Internal server error"}},
    ])

    assert not [c for c in chunks if (c.get("choices") or [{}])[0].get("delta", {}).get("tool_calls")]
    errors = [c for c in chunks if c.get("error")]
    assert len(errors) == 1
    assert errors[0]["status_code"] == 500
    assert "Internal server error" in errors[0]["message"]
