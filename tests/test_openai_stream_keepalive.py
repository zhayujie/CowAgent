"""Cap keep-alive-only streams in the shared OpenAI-compatible HTTP client.

DeepSeek, Moonshot, MiMo (#3892), Doubao, MiniMax, LinkAI, ModelScope (#3909)
and Gemini (#3912) stop a stream that only sends ``": keep-alive"`` comments.
``OpenAIHTTPClient`` (used by the OpenAI, Azure and OpenAI-compatible bots)
reads SSE with ``iter_content`` instead of ``iter_lines``, so it was not part of
that scan: each comment still resets ``requests``' per-read timeout and is
silently dropped, so an overloaded endpoint can hold the turn forever.
"""

from types import SimpleNamespace

import pytest

from models.openai import openai_http_client as client_module
from models.openai.openai_http_client import OpenAIHTTPClient

KEEPALIVE = b": keep-alive\n\n"
DATA = b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
DONE = b"data: [DONE]\n\n"


class FakeResponse:
    status_code = 200

    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def iter_content(self, **kwargs):
        yield from self._chunks

    def close(self):
        self.closed = True


def _stream(monkeypatch, chunks, tick_seconds=1, limit=None):
    response = FakeResponse(chunks)
    monkeypatch.setattr(client_module.requests, "post", lambda *a, **kw: response)
    clock = iter(range(0, tick_seconds * (len(chunks) + 10), tick_seconds))
    monkeypatch.setattr(client_module, "time", SimpleNamespace(time=lambda: next(clock)), raising=False)
    if limit is not None:
        monkeypatch.setattr(client_module, "STREAM_KEEPALIVE_MAX_SECONDS", limit, raising=False)
    client = OpenAIHTTPClient(api_key="k", api_base="http://stream.invalid/v1")
    chunks_out = list(client.chat_completions(model="m", messages=[], stream=True))
    return chunks_out, response


def test_a_keepalive_only_stream_fails_instead_of_hanging(monkeypatch):
    chunks, response = _stream(monkeypatch, [KEEPALIVE] * 5, tick_seconds=100, limit=150)

    assert len(chunks) == 1, f"a keep-alive-only stream yielded {chunks}"
    assert chunks[0]["status_code"] == 504, "the caller must be able to retry this"
    assert "keep-alive" in chunks[0]["message"]
    assert response.closed


def test_keepalives_between_data_do_not_trip_the_cap(monkeypatch):
    chunks, _ = _stream(
        monkeypatch, [KEEPALIVE, DATA, KEEPALIVE, DATA, DONE], tick_seconds=100, limit=150
    )

    assert not any(c.get("error") for c in chunks), chunks
    assert [c["choices"][0]["delta"]["content"] for c in chunks] == ["hi", "hi"]


def test_ordinary_data_still_parses(monkeypatch):
    chunks, _ = _stream(monkeypatch, [DATA, DONE])

    assert [c["choices"][0]["delta"]["content"] for c in chunks] == ["hi"]


@pytest.mark.parametrize("split", [1, 3, 7])
def test_cap_works_when_comments_are_split_across_network_chunks(monkeypatch, split):
    stream = KEEPALIVE * 5
    pieces = [stream[i:i + split] for i in range(0, len(stream), split)]
    chunks, _ = _stream(monkeypatch, pieces, tick_seconds=100, limit=150)

    assert len(chunks) == 1 and chunks[0]["status_code"] == 504, chunks
