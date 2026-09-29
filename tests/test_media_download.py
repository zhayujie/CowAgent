"""Shared size-capped media downloads used by the IM channels."""

import pytest
import requests

from common import media_download
from common.media_download import MediaTooLargeError, download_bytes, download_to_file


class Response:
    def __init__(self, chunks=(b"media",), headers=None, status_code=200, interrupt=False):
        self.chunks = chunks
        self.headers = headers or {}
        self.status_code = status_code
        self.interrupt = interrupt
        self.closed = False
        self.iterated = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        self.iterated = True
        for chunk in self.chunks:
            yield chunk
            if self.interrupt:
                raise OSError("connection lost")

    def close(self):
        self.closed = True


@pytest.fixture
def serve(monkeypatch):
    calls = []

    def install(response):
        def get(url, **kwargs):
            calls.append(dict(kwargs, url=url))
            return response

        monkeypatch.setattr(media_download.requests, "get", get)
        return calls

    return install


def test_file_is_streamed_into_place(tmp_path, serve):
    response = Response(chunks=(b"ab", b"", b"cd"), headers={"Content-Type": "image/png"})
    calls = serve(response)
    target = tmp_path / "out.png"

    result = download_to_file("https://example.test/a", str(target), 10, timeout=7, headers={"X": "1"})

    assert target.read_bytes() == b"abcd"
    assert result == (4, "image/png")
    assert calls == [{"url": "https://example.test/a", "stream": True, "timeout": 7, "headers": {"X": "1"}}]
    assert list(tmp_path.iterdir()) == [target]
    assert response.closed


def test_declared_oversize_is_rejected_before_reading(tmp_path, serve):
    response = Response(headers={"Content-Length": "11"})
    serve(response)

    with pytest.raises(MediaTooLargeError):
        download_to_file("https://example.test/a", str(tmp_path / "out"), 10)

    assert not response.iterated
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_malformed_content_length_still_hits_streamed_cap(tmp_path, serve):
    response = Response(chunks=(b"123456", b"789012"), headers={"Content-Length": "abc"})
    serve(response)

    with pytest.raises(MediaTooLargeError):
        download_to_file("https://example.test/a", str(tmp_path / "out"), 10)

    assert list(tmp_path.iterdir()) == []
    assert response.closed


@pytest.mark.parametrize("response", [
    Response(status_code=404),
    Response(chunks=(b"partial", b"rest"), interrupt=True),
    Response(chunks=(b"123456", b"789012")),
])
def test_failure_keeps_existing_file_and_leaves_no_temp(tmp_path, serve, response):
    serve(response)
    target = tmp_path / "out"
    target.write_bytes(b"previous")

    with pytest.raises((requests.HTTPError, OSError, MediaTooLargeError)):
        download_to_file("https://example.test/a", str(target), 10)

    assert target.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [target]
    assert response.closed


def test_bytes_download_is_capped(serve):
    ok = Response(chunks=(b"ab", b"cd"))
    serve(ok)
    assert download_bytes("https://example.test/a", 4) == b"abcd"
    assert ok.closed

    too_big = Response(chunks=(b"ab", b"cde"))
    serve(too_big)
    with pytest.raises(MediaTooLargeError):
        download_bytes("https://example.test/a", 4)
    assert too_big.closed


def test_bytes_download_raises_on_http_error(serve):
    response = Response(status_code=500)
    serve(response)

    with pytest.raises(requests.HTTPError):
        download_bytes("https://example.test/a")

    assert not response.iterated
    assert response.closed
