# encoding:utf-8
"""The Claude 3 line rejects an oversized max_tokens instead of clamping it.

Anthropic answers ``max_tokens: 64000 > 4096, which is the maximum allowed
number of output tokens for claude-3-haiku-20240307`` with a 400, so asking for
the 64K default on a 3.x model fails the whole turn rather than truncating it.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from common import const
from models.claudeapi import claude_api_bot

# Every 3.x id the config offers: CLAUDE3 / CLAUDE_3_OPUS / _0229 / SONNET /
# HAIKU in common/const.py, plus the bare aliases _model_mapping accepts.
LEGACY_3X = [
    const.CLAUDE3,
    const.CLAUDE_3_OPUS,
    const.CLAUDE_3_OPUS_0229,
    const.CLAUDE_3_SONNET,
    const.CLAUDE_3_HAIKU,
    "claude-3-opus",
    "claude-3-sonnet",
    "claude-3-haiku",
]


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}


def _request_body(monkeypatch, model):
    """The JSON body the bot would post for *model* (no network)."""
    from config import conf

    captured = {}

    def post(url, **kwargs):
        captured.setdefault("body", kwargs["json"])
        return _Response()

    bot = claude_api_bot.ClaudeAPIBot.__new__(claude_api_bot.ClaudeAPIBot)
    monkeypatch.setitem(conf(), "claude_api_key", "k")
    monkeypatch.setitem(conf(), "claude_api_base", "https://api.anthropic.com/v1")
    monkeypatch.setitem(conf(), "proxy", None)
    monkeypatch.setitem(conf(), "model", model)
    monkeypatch.setitem(conf(), "character_desc", "")
    monkeypatch.setattr(claude_api_bot.requests, "post", post)

    bot.reply_text(SimpleNamespace(messages=[{"role": "user", "content": "hi"}]))
    return captured["body"]


@pytest.mark.parametrize("model", LEGACY_3X)
def test_a_3x_model_asks_for_no_more_than_its_output_cap(monkeypatch, model):
    body = _request_body(monkeypatch, model)

    assert body["max_tokens"] <= 4096, (
        f"{model} caps output at 4096; max_tokens={body['max_tokens']} is a 400"
    )


@pytest.mark.parametrize("model,expected", [
    (const.CLAUDE_35_SONNET, 8192),
    (const.CLAUDE_35_SONNET_0620, 8192),
    ("claude-sonnet-4-8", 64000),
    ("claude-opus-5-5", 64000),
    # A model released after this fix must keep the 64K default.
    ("claude-something-7", 64000),
])
def test_the_cap_still_tracks_the_generation(monkeypatch, model, expected):
    assert _request_body(monkeypatch, model)["max_tokens"] == expected
