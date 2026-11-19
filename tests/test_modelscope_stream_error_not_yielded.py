# encoding:utf-8
"""A mid-stream ModelScope failure must reach the consumer as an error chunk."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.modelscope.modelscope_bot import ModelScopeBot


def _dying_lines():
    yield b'data: {"choices": [{"delta": {"content": "partial"}}]}'
    raise OSError("connection reset by peer")


def test_mid_stream_failure_yields_error_chunk_after_partial_text():
    bot = ModelScopeBot.__new__(ModelScopeBot)
    bot.api_key, bot.base_url = "test-key", "http://localhost"
    session = MagicMock(messages=[{"role": "user", "content": "hi"}])
    response = MagicMock(status_code=200, text="")
    response.iter_lines.side_effect = _dying_lines
    with patch("models.modelscope.modelscope_bot.requests.post", return_value=response):
        chunks = list(bot._handle_stream_response(session, {"model": "Qwen/Qwen3-8B"}))

    assert chunks[0]["choices"][0]["delta"]["content"] == "partial"
    errors = [c for c in chunks if c.get("error")]
    assert len(errors) == 1
    assert errors[0]["status_code"] == 500
    assert "connection reset by peer" in str(errors[0]["message"])

def _usage_trailer_lines():
    """An unsolicited usage stream: content, then a usage-only
    trailer whose choices list is present but empty."""
    yield b'data: {"choices": [{"delta": {"content": "the full answer"}}]}'
    yield b'data: {"usage": {"total_tokens": 42, "completion_tokens": 7}, "choices": []}'
    yield b'data: [DONE]'


def test_usage_trailer_does_not_discard_the_streamed_reply():
    """choices may be present but empty; indexing it lost the whole reply.

    `json_data.get("choices", [{}])[0]` only defaults when the key is missing, so
    the trailer raised IndexError. That escaped the JSONDecodeError handler and
    reached the outer catch-all, which replaced the finished answer with a canned
    "come back later" message and zeroed the usage it had just parsed.
    """
    bot = ModelScopeBot.__new__(ModelScopeBot)
    bot.api_key, bot.base_url = "test-key", "http://localhost"
    session = MagicMock(messages=[{"role": "user", "content": "hi"}])
    response = MagicMock(status_code=200, text="")
    response.iter_lines.side_effect = _usage_trailer_lines
    with patch("models.modelscope.modelscope_bot.requests.post", return_value=response):
        result = bot.reply_text_stream(session, args={"model": "Qwen/Qwen3-8B"})

    assert result["content"] == "the full answer"
    assert result["total_tokens"] == 42
    assert result["completion_tokens"] == 7


def _absent_choices_lines():
    """A chunk with no choices key at all must still be tolerated."""
    yield b'data: {"choices": [{"delta": {"content": "hi"}}]}'
    yield b'data: {"usage": {"total_tokens": 5, "completion_tokens": 1}}'
    yield b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}'
    yield b'data: [DONE]'


def test_a_chunk_without_a_choices_key_is_still_tolerated():
    bot = ModelScopeBot.__new__(ModelScopeBot)
    bot.api_key, bot.base_url = "test-key", "http://localhost"
    session = MagicMock(messages=[{"role": "user", "content": "hi"}])
    response = MagicMock(status_code=200, text="")
    response.iter_lines.side_effect = _absent_choices_lines
    with patch("models.modelscope.modelscope_bot.requests.post", return_value=response):
        result = bot.reply_text_stream(session, args={"model": "Qwen/Qwen3-8B"})

    assert result["content"] == "hi"
    assert result["total_tokens"] == 5
