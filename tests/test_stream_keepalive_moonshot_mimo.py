"""An SSE stream that carries only keep-alive comments must not hang the turn.

Moonshot and MiMo parse the OpenAI-compatible SSE stream with the same block
DeepSeek used: any line that is not `data:` is skipped, and the socket read
timeout is per-read, so a server that holds the request open with only
": keep-alive" comments keeps resetting it. Nothing reaches the caller, so the
turn sits there for as long as the server likes, cancel is never noticed, and
the next message in the session waits behind it — the same failure DeepSeek was
just fixed for.

Both bots should now forward an empty chunk per keep-alive (so the caller's
cancel probe runs) and give up with a retryable 504 once only keep-alives have
arrived for STREAM_KEEPALIVE_MAX_SECONDS.

The first two cases fail on the old code, which yields nothing at all for a
keep-alive-only stream; the third is the control that ordinary data still
parses.
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.mimo import mimo_bot  # noqa: E402
from models.moonshot import moonshot_bot  # noqa: E402

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
        for line in self._lines:
            yield line

    def close(self):
        self.closed = True


def _provider_param():
    return [
        pytest.param(moonshot_bot, "MoonshotBot", "base_url", id="moonshot"),
        pytest.param(mimo_bot, "MimoBot", "api_base", id="mimo"),
    ]


def _make_bot(mod, class_name, base_attr, monkeypatch):
    cls = getattr(mod, class_name)
    cls = getattr(cls, "__wrapped__", cls)
    # base_url / api_base are properties reading conf(), so pin the class
    # attribute instead of the instance.
    monkeypatch.setattr(cls, base_attr, property(lambda self: "http://stream.invalid"), raising=False)
    bot = cls.__new__(cls)
    bot._build_headers = lambda: {}
    return bot


def _run(mod, class_name, base_attr, lines, monkeypatch, tick_seconds):
    """Drive the provider's stream handler over `lines` with a fake clock."""
    response = FakeResponse(lines)
    monkeypatch.setattr(mod.requests, "post", lambda *a, **kw: response)
    ticks = iter(range(0, tick_seconds * (len(lines) + 2), tick_seconds))
    monkeypatch.setattr(mod, "time", SimpleNamespace(time=lambda: next(ticks)))
    bot = _make_bot(mod, class_name, base_attr, monkeypatch)
    return list(bot._handle_stream_response({"model": "m", "messages": []}))


@pytest.mark.parametrize("mod,class_name,base_attr", _provider_param())
def test_a_keepalive_only_stream_fails_instead_of_hanging(mod, class_name, base_attr, monkeypatch):
    monkeypatch.setattr(mod, "STREAM_KEEPALIVE_MAX_SECONDS", 0, raising=False)
    chunks = _run(mod, class_name, base_attr, [KEEPALIVE] * 3, monkeypatch, tick_seconds=100)

    errors = [c for c in chunks if c.get("error")]
    assert len(errors) == 1, f"a keep-alive-only stream yielded {chunks}"
    assert errors[0]["status_code"] == 504, "the caller must be able to retry this"
    assert "keep-alive" in errors[0]["message"]


@pytest.mark.parametrize("mod,class_name,base_attr", _provider_param())
def test_keepalive_forwards_an_empty_chunk_so_cancel_can_run(mod, class_name, base_attr, monkeypatch):
    chunks = _run(
        mod, class_name, base_attr,
        [KEEPALIVE, KEEPALIVE, DATA, DONE],
        monkeypatch, tick_seconds=1,
    )

    assert chunks[:2] == [{}, {}], (
        f"each keep-alive must reach the caller as an empty chunk, got {chunks[:2]}"
    )
    assert not any(c.get("error") for c in chunks)


@pytest.mark.parametrize("mod,class_name,base_attr", _provider_param())
def test_ordinary_data_still_parses(mod, class_name, base_attr, monkeypatch):
    chunks = _run(mod, class_name, base_attr, [DATA, DONE], monkeypatch, tick_seconds=1)

    texts = [
        c["choices"][0]["delta"].get("content")
        for c in chunks
        if isinstance(c.get("choices"), list) and c["choices"]
    ]
    assert [t for t in texts if t] == ["hi"], f"content chunks were {chunks}"
    assert not any(c.get("error") for c in chunks)
    json.dumps(chunks)  # the forwarded {} must stay JSON-serialisable
