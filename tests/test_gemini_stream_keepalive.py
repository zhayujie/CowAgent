"""Cap a Gemini REST stream that receives nothing but SSE keep-alive comments.

DeepSeek (``122285d3``), Moonshot/MiMo (#3892) and then Doubao/MiniMax/LinkAI/
ModelScope (#3909) were each given a guard for an overloaded endpoint that
holds a request open with only ``": keep-alive"`` comments: every comment
resets the socket's per-read timeout, and skipping it hands nothing back to
the caller, so the turn hangs and the cancel probe never runs. Those seven
providers all parse OpenAI-compatible SSE. Gemini's REST path uses Google's
``alt=sse`` envelope with a different loop: it strips ``data: `` and feeds
everything else to ``json.loads`` inside ``except json.JSONDecodeError:
continue``. A comment line therefore also disappears without a trace.

It is the last ``iter_lines()`` loop in ``models/`` without the guard
(claudeapi has its own ``_StallWatchdog``). #3909's PR body named this loop
and offered to audit it separately; #3909 was merged.

Each case drives the real handler with a fake SSE response and a fake clock
that advances once per line, so the 180-second cap is measured rather than
patched away.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.gemini import google_gemini_bot as gemini  # noqa: E402

KEEPALIVE = b": keep-alive"
PING = b": ping"
DATA = b'data: {"candidates":[{"content":{"parts":[{"text":"hello"}]}}]}'


class _Clock:
    """Only ``time.time()`` is used by this module (for chunk ids)."""

    def __init__(self, start=1000.0):
        self.now = start

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _FakeSSE:
    def __init__(self, lines, clock, tick_seconds):
        self._lines = lines
        self._clock = clock
        self._tick = tick_seconds

    def iter_lines(self):
        for line in self._lines:
            self._clock.advance(self._tick)
            yield line


def _run(monkeypatch, lines, tick_seconds=1):
    clock = _Clock()
    monkeypatch.setattr(gemini, "time", clock)
    bot = gemini.GoogleGeminiBot.__new__(gemini.GoogleGeminiBot)
    response = _FakeSSE(lines, clock, tick_seconds)
    return list(bot._handle_gemini_rest_stream_response(response, "gemini-2.5-flash"))


def _errors(chunks):
    return [c for c in chunks if c.get("error")]


def _texts(chunks):
    return [
        c["choices"][0]["delta"]["content"]
        for c in chunks
        if c.get("choices")
        and c["choices"][0].get("delta", {}).get("content")
    ]


def test_a_keepalive_only_stream_ends_in_a_retryable_504(monkeypatch):
    """Twelve comments 20s apart pass the cap: the caller must get a 504."""
    chunks = _run(monkeypatch, [KEEPALIVE] * 12, tick_seconds=20)

    errors = _errors(chunks)
    assert len(errors) == 1, f"a keep-alive-only stream yielded {chunks}"
    assert errors[0]["status_code"] == 504, "the caller must be able to retry this"
    assert "keep-alive" in errors[0]["message"]


def test_each_keepalive_hands_control_back_for_the_cancel_probe(monkeypatch):
    """An empty chunk per comment lets the caller notice a user cancel."""
    chunks = _run(monkeypatch, [KEEPALIVE, PING, DATA])

    assert chunks[:2] == [{}, {}], (
        f"each keep-alive must reach the caller as an empty chunk, got {chunks[:2]}"
    )
    assert not _errors(chunks)
    assert _texts(chunks) == ["hello"]


def test_a_keepalive_only_stream_does_not_pretend_to_be_an_empty_answer(monkeypatch):
    """Without the guard the loop falls out and emits a normal 'stop' chunk."""
    chunks = _run(monkeypatch, [KEEPALIVE] * 12, tick_seconds=20)

    normal_stops = [
        c for c in chunks
        if c.get("choices") and c["choices"][0].get("finish_reason") == "stop"
    ]
    assert not normal_stops, (
        "an empty answer hides the failure; the user must see a timeout instead"
    )


def test_keepalives_below_the_cap_do_not_fail_the_stream(monkeypatch):
    """Five comments 20s apart are still a healthy (100s) wait."""
    chunks = _run(monkeypatch, [KEEPALIVE] * 5, tick_seconds=20)

    assert len([c for c in chunks if c == {}]) == 5, f"got {chunks}"
    assert not _errors(chunks)


def test_a_real_data_chunk_resets_the_keepalive_clock(monkeypatch):
    """160s of comments, one real chunk, 160s more: neither half exceeds 180s."""
    lines = [KEEPALIVE] * 8 + [DATA] + [KEEPALIVE] * 8
    chunks = _run(monkeypatch, lines, tick_seconds=20)

    assert not _errors(chunks), f"normal data must reset the clock, got {chunks}"
    assert _texts(chunks) == ["hello"]


@pytest.mark.parametrize("lines", [
    [DATA],
    [KEEPALIVE, DATA, PING],
])
def test_an_ordinary_stream_is_unchanged(monkeypatch, lines):
    """Controls: green on both sides, so the guard cannot silently break data."""
    chunks = _run(monkeypatch, lines)

    assert not _errors(chunks)
    assert _texts(chunks) == ["hello"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
