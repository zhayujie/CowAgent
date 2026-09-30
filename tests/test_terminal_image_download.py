import io
from types import SimpleNamespace

import requests
from PIL import Image

from bridge.reply import Reply, ReplyType
from channel.terminal.terminal_channel import TerminalChannel


class FakeResponse:
    def __init__(self, chunks, status_code=200, headers=None):
        self.chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield from self.chunks

    def close(self):
        self.closed = True


def test_terminal_rejects_oversized_image_and_closes_response(monkeypatch, capsys):
    response = FakeResponse([b"x" * (10 * 1024 * 1024 + 1)])
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(Image, "open", lambda *args: (_ for _ in ()).throw(
        AssertionError("oversized response must not reach the decoder")
    ))

    TerminalChannel().send(Reply(ReplyType.IMAGE_URL, "https://example.com/a.png"), None)

    assert response.closed
    assert "Image unavailable" in capsys.readouterr().out


def test_terminal_image_request_is_bounded_and_http_errors_are_reported(monkeypatch, capsys):
    response = FakeResponse([], status_code=404)
    calls = []

    def get(*args, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(requests, "get", get)

    TerminalChannel().send(Reply(ReplyType.IMAGE_URL, "https://example.com/missing.png"), None)

    assert calls[0]["stream"] is True
    assert calls[0]["timeout"] == (5, 15)
    assert response.closed
    assert "Image unavailable" in capsys.readouterr().out


def test_terminal_rejects_large_content_length_without_reading_body(monkeypatch, capsys):
    response = FakeResponse([], headers={"Content-Length": str(10 * 1024 * 1024 + 1)})

    def fail_if_read(*_args, **_kwargs):
        raise AssertionError("oversized body must not be read")

    response.iter_content = fail_if_read
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    TerminalChannel().send(Reply(ReplyType.IMAGE_URL, "https://example.com/large.png"), None)

    assert response.closed
    assert "Image unavailable" in capsys.readouterr().out


def test_terminal_still_displays_valid_image_and_closes_response(monkeypatch, capsys):
    storage = io.BytesIO()
    Image.new("RGB", (1, 1), "red").save(storage, format="PNG")
    response = FakeResponse([storage.getvalue()])
    shown = []
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(Image.Image, "show", lambda self: shown.append(self.size))

    TerminalChannel().send(Reply(ReplyType.IMAGE_URL, "https://example.com/a.png"), None)

    assert shown == [(1, 1)]
    assert response.closed
    assert "https://example.com/a.png" in capsys.readouterr().out


def test_terminal_stops_a_slow_image_stream(monkeypatch, capsys):
    response = FakeResponse([b"a", b"b"])
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    times = iter([0, 1, 61])
    monkeypatch.setattr(
        "channel.terminal.terminal_channel.time",
        SimpleNamespace(monotonic=lambda: next(times)),
    )

    TerminalChannel().send(Reply(ReplyType.IMAGE_URL, "https://example.com/slow.png"), None)

    assert response.closed
    assert "Image unavailable" in capsys.readouterr().out


def test_terminal_rejects_excessive_image_dimensions_before_decode(monkeypatch, capsys):
    response = FakeResponse([b"placeholder"])
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    class HugeImage:
        width = 10000
        height = 10000

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def load(self):
            raise AssertionError("oversized image must not be decoded")

    monkeypatch.setattr(Image, "open", lambda *_: HugeImage())

    TerminalChannel().send(Reply(ReplyType.IMAGE_URL, "https://example.com/huge.png"), None)

    assert response.closed
    assert "Image unavailable" in capsys.readouterr().out
