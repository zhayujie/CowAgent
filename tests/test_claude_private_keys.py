# encoding:utf-8
"""Anthropic rejects unknown message fields, so in-memory markers must not ship.

``agent_stream`` stores Gemini's ``_gemini_raw_parts`` on the assistant message
in the shared history. A session that switches from Gemini to Claude keeps that
message, and the API answers ``extra fields are not permitted`` with a 400 on
every turn until the message ages out of the context window.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import conf
from models.claudeapi import claude_api_bot


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}


def _bot(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.setdefault("body", kwargs["json"])
        return _Response()

    bot = claude_api_bot.ClaudeAPIBot.__new__(claude_api_bot.ClaudeAPIBot)
    monkeypatch.setitem(conf(), "claude_api_key", "k")
    monkeypatch.setitem(conf(), "claude_api_base", "https://api.anthropic.com/v1")
    monkeypatch.setitem(conf(), "proxy", None)
    monkeypatch.setitem(conf(), "model", "claude-sonnet-4-5")
    monkeypatch.setitem(conf(), "character_desc", "")
    monkeypatch.setattr(claude_api_bot.requests, "post", post)
    return bot, captured


def _poisoned_history():
    """A history left behind by a Gemini turn: the marker sits on the message."""
    return [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "hello"}],
            "_gemini_raw_parts": [{"text": "hello", "thoughtSignature": "sig"}],
        },
        {"role": "user", "content": "again"},
    ]


def test_the_agent_path_does_not_send_the_gemini_marker(monkeypatch):
    bot, captured = _bot(monkeypatch)

    bot.call_with_tools(_poisoned_history(), stream=False)

    sent = captured["body"]["messages"]
    assert all("_gemini_raw_parts" not in msg for msg in sent), (
        f"Anthropic 400s on unknown fields, got: {sent}"
    )


def test_the_legacy_path_does_not_send_the_gemini_marker(monkeypatch):
    """`reply_text` builds its own body and used to forward the history verbatim."""
    bot, captured = _bot(monkeypatch)

    bot.reply_text(SimpleNamespace(messages=_poisoned_history()))

    sent = captured["body"]["messages"]
    assert all("_gemini_raw_parts" not in msg for msg in sent), (
        f"the legacy path leaks the marker too: {sent}"
    )


def test_only_the_marker_is_dropped(monkeypatch):
    bot, captured = _bot(monkeypatch)

    bot.call_with_tools(_poisoned_history(), stream=False)

    assert captured["body"]["messages"][1] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "hello"}],
    }


def test_the_shared_history_is_not_mutated(monkeypatch):
    bot, _ = _bot(monkeypatch)
    history = _poisoned_history()

    bot.call_with_tools(history, stream=False)

    assert "_gemini_raw_parts" in history[1], "the agent still needs it for Gemini"


def test_unsigned_thinking_is_still_dropped(monkeypatch):
    """The pre-existing sanitising must keep working alongside the new strip."""
    bot, captured = _bot(monkeypatch)
    history = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hmm"},
                {"type": "text", "text": "hello"},
            ],
            "_gemini_raw_parts": [],
        },
    ]

    bot.call_with_tools(history, stream=False)

    assert captured["body"]["messages"][1]["content"] == [
        {"type": "text", "text": "hello"}
    ]


def test_a_signed_thinking_block_is_still_sent_back(monkeypatch):
    bot, captured = _bot(monkeypatch)
    signed = {"type": "thinking", "thinking": "hmm", "signature": "sig"}
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [signed, {"type": "text", "text": "hello"}]},
    ]

    bot.call_with_tools(history, stream=False)

    assert captured["body"]["messages"][1]["content"][0] == signed
