"""WeCom reply downloads must never publish unbounded or partial media."""

import pytest
import requests

from channel.wecom_bot import wecom_bot_channel as channel


class Response:
    def __init__(self, chunks=(b"media",), headers=None, error=None, interrupt=False):
        self.chunks = chunks
        self.headers = headers or {}
        self.error = error
        self.interrupt = interrupt
        self.closed = False

    def raise_for_status(self):
        if self.error:
            raise self.error

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            yield chunk
            if self.interrupt:
                raise OSError("connection lost")

    def close(self):
        self.closed = True


def _patch_download(monkeypatch, tmp_path, response):
    calls = []

    def get(*args, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(channel.requests, "get", get)
    monkeypatch.setattr(
        channel, "_media_tmp_path", lambda prefix, ext="": str(tmp_path / f"{prefix}{ext}")
    )
    return calls


def test_small_media_is_streamed_to_managed_temp_file(monkeypatch, tmp_path):
    response = Response(chunks=(b"media",), headers={"Content-Type": "image/png"})
    calls = _patch_download(monkeypatch, tmp_path, response)

    path, size, content_type = channel._download_remote_media(
        "https://example.test/image", "wecom_img", None, 100, 30
    )

    assert path == str(tmp_path / "wecom_img.png")
    assert (tmp_path / "wecom_img.png").read_bytes() == b"media"
    assert size == 5 and content_type == "image/png"
    assert calls == [{"stream": True, "timeout": (5, 30)}]
    assert response.closed


def test_declared_oversize_never_opens_destination(monkeypatch, tmp_path):
    response = Response(headers={"Content-Length": "101"})
    _patch_download(monkeypatch, tmp_path, response)

    with pytest.raises(ValueError, match="too large"):
        channel._download_remote_media("https://example.test/file", "wecom_file", ".pdf", 100, 60)

    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_streamed_overflow_removes_partial_file(monkeypatch, tmp_path):
    response = Response(chunks=(b"12345", b"67890"))
    _patch_download(monkeypatch, tmp_path, response)

    with pytest.raises(ValueError, match="too large"):
        channel._download_remote_media("https://example.test/file", "wecom_file", ".pdf", 8, 60)

    assert list(tmp_path.iterdir()) == []
    assert response.closed


@pytest.mark.parametrize("response", [
    Response(error=requests.HTTPError("404")),
    Response(chunks=(b"partial",), interrupt=True),
])
def test_failed_transfer_closes_response_and_cleans_up(monkeypatch, tmp_path, response):
    _patch_download(monkeypatch, tmp_path, response)

    with pytest.raises((requests.HTTPError, OSError)):
        channel._download_remote_media("https://example.test/file", "wecom_file", ".pdf", 100, 60)

    assert list(tmp_path.iterdir()) == []
    assert response.closed
