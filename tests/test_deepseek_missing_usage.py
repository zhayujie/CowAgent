# encoding:utf-8
"""A 200 without `usage` must not throw away the answer it carries.

`deepseek_api_base` can point at a self-hosted proxy or an OpenAI-compatible
gateway that omits `usage`. `reply_text` indexed it, the KeyError went to the
blanket `except Exception` (which retries three times), and the caller got
`completion_tokens=0`, which `reply()` reads as an error — the model's real
answer replaced by "我现在有点累了，等会再来吧".
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

from models.deepseek import deepseek_bot


def _bot(monkeypatch, payload, calls=None):
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: {
        "deepseek_api_key": "k",
        "model": "deepseek-chat",
    }.get(key, default))
    monkeypatch.setattr(deepseek_bot, "conf", cfg)
    monkeypatch.setattr(deepseek_bot, "SessionManager", MagicMock())
    bot = deepseek_bot.DeepSeekBot()

    def post(url, **kwargs):
        if calls is not None:
            calls.append(kwargs.get("json"))
        res = MagicMock()
        res.status_code = 200
        res.json.return_value = payload
        return res

    monkeypatch.setattr(deepseek_bot.requests, "post", post)
    return bot


def _session():
    return SimpleNamespace(messages=[{"role": "user", "content": "hi"}])


def _answer(text="real answer"):
    return {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}]}


def test_an_answer_survives_a_response_without_usage(monkeypatch):
    calls = []
    bot = _bot(monkeypatch, _answer(), calls)

    reply = bot.reply_text(_session())

    assert reply["content"] == "real answer"
    assert reply["completion_tokens"] > 0, "reply() would report this as an error"
    assert len(calls) == 1, "the same call was retried for a missing usage field"


def test_reported_usage_is_still_used_verbatim(monkeypatch):
    payload = _answer()
    payload["usage"] = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    bot = _bot(monkeypatch, payload)

    reply = bot.reply_text(_session())

    assert (reply["total_tokens"], reply["completion_tokens"]) == (18, 7)


def test_an_empty_200_does_not_raise(monkeypatch):
    """A gateway can answer 200 with no body at all; that is not an exception."""
    bot = _bot(monkeypatch, {})

    reply = bot.reply_text(_session())

    assert reply["content"] == ""
    assert reply["completion_tokens"] == 0
