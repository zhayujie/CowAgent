"""Regression tests for the Feishu image-URL upload path."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from channel.feishu.feishu_channel import FeiShuChanel

IMG_URL = "https://cdn.example.com/chart.png"


class DownloadResponse:
    def __init__(self, status_code=200, content=b"png-bytes", headers=None, interrupt=False):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.interrupt = interrupt
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        yield self.content
        if self.interrupt:
            raise OSError("connection lost")

    def close(self):
        self.closed = True


def _channel():
    # _upload_image_url does not touch instance state, and the class is wrapped
    # by @singleton, so build a bare instance from the undecorated class instead
    # of starting a channel.
    cls = FeiShuChanel.__wrapped__
    return cls.__new__(cls)


def _ok_upload(image_key="img_v2_chart"):
    def post(url, files=None, data=None, headers=None, timeout=None):
        post.calls.append({"url": url, "files": files, "timeout": timeout})
        return SimpleNamespace(
            content=b"{}", json=lambda: {"code": 0, "data": {"image_key": image_key}}
        )

    post.calls = []
    return post


def test_failed_download_returns_none_instead_of_raising(tmp_path, monkeypatch):
    # A non-200 leaves nothing to upload. The caller handles that by checking the
    # return value (`if not reply_content: logger.warning("upload image failed")`),
    # so the failure has to arrive as None rather than as FileNotFoundError.
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse(status_code=500, content=b"<html>oops</html>")
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            result = _channel()._upload_image_url(IMG_URL, "token")

    assert result is None
    assert post.calls == []
    assert list(tmp_path.iterdir()) == []


def test_download_is_bounded_and_uploaded_from_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse()
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response) as get:
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            result = _channel()._upload_image_url(IMG_URL, "token")

    assert result == "img_v2_chart"
    # Both legs of the round trip are bounded.
    assert get.call_args.kwargs["timeout"] == (5, 30)
    assert get.call_args.kwargs["stream"] is True
    assert response.closed
    assert post.calls[0]["timeout"] == (5, 15)
    # The downloaded bytes are the multipart payload; nothing is staged on disk.
    name, payload = post.calls[0]["files"]["image"]
    assert (name, payload) == ("image.png", b"png-bytes")
    assert list(tmp_path.iterdir()) == []


def test_upload_failure_leaves_nothing_behind(tmp_path, monkeypatch):
    # Staging the download in a file meant a failed upload kept it in the working
    # directory for good: the cleanup ran only after a successful response.
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch(
            "channel.feishu.feishu_channel.requests.post",
            side_effect=RuntimeError("connection reset"),
        ):
            with pytest.raises(RuntimeError):
                _channel()._upload_image_url(IMG_URL, "token")

    assert list(tmp_path.iterdir()) == []


def test_api_error_code_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse()

    def post(url, files=None, data=None, headers=None, timeout=None):
        return SimpleNamespace(
            content=b"{}", json=lambda: {"code": 99991663, "msg": "no permission"}
        )

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            result = _channel()._upload_image_url(IMG_URL, "token")

    assert result is None


def test_oversized_image_is_not_uploaded(monkeypatch):
    response = DownloadResponse(headers={"Content-Length": str(20 * 1024 * 1024 + 1)})
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            result = _channel()._upload_image_url(IMG_URL, "token")

    assert result is None
    assert post.calls == []
    assert response.closed


def test_interrupted_image_stream_is_not_uploaded(monkeypatch):
    response = DownloadResponse(interrupt=True)
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            result = _channel()._upload_image_url(IMG_URL, "token")

    assert result is None
    assert post.calls == []
    assert response.closed
