"""Cap keep-alive-only streams in the remaining OpenAI-compatible providers.

DeepSeek (:``122285d3``), then Moonshot and MiMo (#3892), were given a guard
for an overloaded endpoint that holds a request open with only
``": keep-alive"`` comments: every comment resets the socket read timeout, and
the loop's ``continue`` hands nothing back to the caller, so the turn hangs and
cancel is never noticed. #3892's commit message named the four providers left
out because their loops skip non-``data:`` lines with a slightly different
spelling; this covers them.

Each case drives the real handler with a fake SSE response and a fake clock.
The first two fail on the old code, which yields nothing for a keep-alive-only
stream; the third is the control that ordinary data still parses.
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.doubao import doubao_bot  # noqa: E402
from models.linkai import link_ai_bot  # noqa: E402
from models.minimax import minimax_bot  # noqa: E402
from models.modelscope import modelscope_bot  # noqa: E402

KEEPALIVE = b": keep-alive"
DATA = b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}'
DONE = b"data: [DONE]"


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, lines):
        self._lines = lines
        self.closed = False

    def iter_lines(self):
        yield from self._lines

    def close(self):
        self.closed = True


def _provider_param():
    return [
        pytest.param(
            doubao_bot, "DoubaoBot",
            {"api_key": "k", "base_url": "http://stream.invalid"},
            lambda bot: bot._handle_stream_response({"model": "m", "messages": []}),
            id="doubao",
        ),
        pytest.param(
            minimax_bot, "MinimaxBot",
            {"api_key": "k", "api_base": "http://stream.invalid"},
            lambda bot: bot._handle_stream_response({"model": "m", "messages": []}),
            id="minimax",
        ),
        pytest.param(
            link_ai_bot, None, {},
            lambda bot: link_ai_bot._handle_linkai_stream_response(
                None, "http://stream.invalid/v1", {}, {"model": "m"}
            ),
            id="linkai",
        ),
        pytest.param(
            modelscope_bot, "ModelScopeBot",
            {"api_key": "k", "base_url": "http://stream.invalid"},
            lambda bot: bot._handle_stream_response(SimpleNamespace(messages=[]), {"model": "m"}),
            id="modelscope",
        ),
    ]


def _patch(mod, class_name, attrs, lines, monkeypatch, tick_seconds, timeout):
    response = FakeResponse(lines)
    monkeypatch.setattr(mod.requests, "post", lambda *a, **kw: response)
    ticks = iter(range(0, tick_seconds * (len(lines) + 2), tick_seconds))
    monkeypatch.setattr(
        mod, "time",
        SimpleNamespace(time=lambda: next(ticks), sleep=lambda *_: None),
    )
    if timeout is not None:
        monkeypatch.setattr(mod, "STREAM_KEEPALIVE_MAX_SECONDS", timeout, raising=False)
    if class_name is None:
        return None
    cls = getattr(mod, class_name)
    cls = getattr(cls, "__wrapped__", cls)
    # api_key / base_url are properties reading conf(), so pin the class attribute.
    for name, value in attrs.items():
        monkeypatch.setattr(cls, name, property(lambda self, v=value: v), raising=False)
    return cls.__new__(cls)


def _run(mod, class_name, attrs, invoke, lines, monkeypatch, tick_seconds=1, timeout=None):
    bot = _patch(mod, class_name, attrs, lines, monkeypatch, tick_seconds, timeout)
    return list(invoke(bot))


@pytest.mark.parametrize("mod,class_name,attrs,invoke", _provider_param())
def test_a_keepalive_only_stream_fails_instead_of_hanging(
    mod, class_name, attrs, invoke, monkeypatch
):
    chunks = _run(mod, class_name, attrs, invoke, [KEEPALIVE] * 3,
                  monkeypatch, tick_seconds=100, timeout=0)

    errors = [c for c in chunks if c.get("error")]
    assert len(errors) == 1, f"a keep-alive-only stream yielded {chunks}"
    assert errors[0]["status_code"] == 504, "the caller must be able to retry this"
    assert "keep-alive" in errors[0]["message"]


@pytest.mark.parametrize("mod,class_name,attrs,invoke", _provider_param())
def test_keepalive_forwards_an_empty_chunk_so_cancel_can_run(
    mod, class_name, attrs, invoke, monkeypatch
):
    chunks = _run(mod, class_name, attrs, invoke,
                  [KEEPALIVE, KEEPALIVE, DATA, DONE], monkeypatch, tick_seconds=1)

    assert chunks[:2] == [{}, {}], (
        f"each keep-alive must reach the caller as an empty chunk, got {chunks[:2]}"
    )
    assert not any(c.get("error") for c in chunks)


@pytest.mark.parametrize("mod,class_name,attrs,invoke", _provider_param())
def test_ordinary_data_still_parses(mod, class_name, attrs, invoke, monkeypatch):
    chunks = _run(mod, class_name, attrs, invoke, [DATA, DONE],
                  monkeypatch, tick_seconds=1)

    texts = [
        c["choices"][0]["delta"].get("content")
        for c in chunks
        if isinstance(c.get("choices"), list) and c["choices"]
    ]
    assert [t for t in texts if t] == ["hi"], f"content chunks were {chunks}"
    assert not any(c.get("error") for c in chunks)
    json.dumps(chunks)  # the forwarded {} must stay JSON-serialisable


def _run_reply_text_stream(lines, monkeypatch, tick_seconds=1, timeout=None):
    bot = _patch(
        modelscope_bot, "ModelScopeBot",
        {"api_key": "k", "base_url": "http://stream.invalid"},
        lines, monkeypatch, tick_seconds, timeout,
    )
    return bot.reply_text_stream(SimpleNamespace(messages=[]), {"model": "m"})


def test_the_thinking_model_path_reports_the_timeout(monkeypatch):
    """`reply_text_stream` is synchronous, so it cannot yield; it must still
    stop the loop and say why instead of returning an empty answer."""
    result = _run_reply_text_stream([KEEPALIVE] * 3, monkeypatch, timeout=0)

    assert "超时" in result["content"], f"result was {result}"
    assert result["completion_tokens"] == 0


def test_the_thinking_model_path_still_parses_ordinary_data(monkeypatch):
    result = _run_reply_text_stream([DATA, DONE], monkeypatch)

    assert result["content"] == "hi", f"result was {result}"
    assert result["completion_tokens"] == 0
