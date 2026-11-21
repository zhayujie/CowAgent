"""Gemini's finishReason must reach the caller, not be flattened to "stop".

``agent_stream`` documents why the field matters:

    A turn that returns text and no tool calls looks finished either way, so
    stop_reason is the only thing separating a model that chose to stop from one
    cut off at the output token limit ("length" / "max_tokens").

The REST handlers already captured ``finishReason`` (and logged it on an empty
answer), then hard-coded ``"stop"`` into the chunk they hand back. A truncated
answer therefore looked like a complete one, and a safety-blocked answer looked
like an empty one the agent would retry.
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.gemini import google_gemini_bot as gemini  # noqa: E402


class _Clock:
    def time(self):
        return 1000.0


class _FakeSSE:
    def __init__(self, payloads):
        self._payloads = payloads

    def iter_lines(self):
        for payload in self._payloads:
            yield b"data: " + payload


def _stream(monkeypatch, payloads):
    monkeypatch.setattr(gemini, "time", _Clock())
    bot = gemini.GoogleGeminiBot.__new__(gemini.GoogleGeminiBot)
    return list(bot._handle_gemini_rest_stream_response(_FakeSSE(payloads), "gemini-2.5-flash"))


def _last_finish_reason(chunks):
    with_choices = [c for c in chunks if c.get("choices")]
    return with_choices[-1]["choices"][0]["finish_reason"]


def _sync(monkeypatch, candidate):
    monkeypatch.setattr(gemini, "time", _Clock())
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"candidates": [candidate], "usageMetadata": {}}
    bot = gemini.GoogleGeminiBot.__new__(gemini.GoogleGeminiBot)
    return bot._handle_gemini_rest_sync_response(response, "gemini-2.5-flash")


def _text_candidate(finish_reason):
    return {"content": {"parts": [{"text": "half a sentence"}]}, "finishReason": finish_reason}


def test_a_stream_cut_off_at_the_token_limit_reports_length(monkeypatch):
    chunks = _stream(monkeypatch, [
        b'{"candidates":[{"content":{"parts":[{"text":"half a sentence"}]},"finishReason":"MAX_TOKENS"}]}',
    ])

    assert _last_finish_reason(chunks) == "length"


def test_a_stream_blocked_by_safety_reports_content_filter(monkeypatch):
    chunks = _stream(monkeypatch, [
        b'{"candidates":[{"content":{"parts":[]},"finishReason":"SAFETY","safetyRatings":[]}]}',
    ])

    assert _last_finish_reason(chunks) == "content_filter"


def test_a_sync_answer_cut_off_at_the_token_limit_reports_length(monkeypatch):
    result = _sync(monkeypatch, _text_candidate("MAX_TOKENS"))

    assert result["choices"][0]["finish_reason"] == "length"


def test_a_normal_stream_still_reports_stop(monkeypatch):
    chunks = _stream(monkeypatch, [b'{"candidates":[{"content":{"parts":[{"text":"hello"}]},"finishReason":"STOP"}]}'])

    assert _last_finish_reason(chunks) == "stop"


def test_a_stream_without_a_finish_reason_still_reports_stop(monkeypatch):
    chunks = _stream(monkeypatch, [b'{"candidates":[{"content":{"parts":[{"text":"hello"}]}}]}'])

    assert _last_finish_reason(chunks) == "stop"


def test_a_tool_call_turn_keeps_its_own_finish_reason(monkeypatch):
    result = _sync(monkeypatch, {
        "content": {"parts": [{"functionCall": {"name": "read", "args": {"path": "a.txt"}}}]},
        "finishReason": "STOP",
    })

    assert result["choices"][0]["finish_reason"] == "tool_calls"
