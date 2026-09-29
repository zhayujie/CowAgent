"""Regression tests for the Feishu file-URL upload path.

The HTTP branch of ``_upload_file_url`` staged the download in a uuid-named file
under the process CWD and then called ``os.remove`` from inside the
``with open(...)`` body, so the handle was still held when the delete ran --
a ``PermissionError`` on Windows, raised after the file had already been
uploaded. The upload itself carried no timeout. Same shape as the image path.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from channel.feishu.feishu_channel import FeiShuChanel

FILE_URL = "https://cdn.example.com/report.pdf"


class DownloadResponse:
    def __init__(self, status_code=200, content=b"pdf-bytes", headers=None, interrupt=False):
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
    # _upload_file_url does not touch instance state, and the class is wrapped
    # by @singleton, so build a bare instance from the undecorated class instead
    # of starting a channel.
    cls = FeiShuChanel.__wrapped__
    return cls.__new__(cls)


def _ok_upload(file_key="file_v2_report"):
    def post(url, files=None, data=None, headers=None, timeout=None):
        post.calls.append({"url": url, "files": files, "data": data, "timeout": timeout})
        return SimpleNamespace(
            content=b"{}", json=lambda: {"code": 0, "data": {"file_key": file_key}}
        )

    post.calls = []
    return post


def test_download_is_bounded_and_uploaded_from_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse()
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response) as get:
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            result = _channel()._upload_file_url(FILE_URL, "token")

    assert result == "file_v2_report"
    # Both legs of the round trip are bounded.
    assert get.call_args.kwargs["timeout"] == (5, 30)
    assert get.call_args.kwargs["stream"] is True
    assert response.closed
    assert post.calls[0]["timeout"] == (5, 30)
    # The downloaded bytes are the multipart payload; nothing is staged on disk.
    assert post.calls[0]["files"]["file"] == ("report.pdf", b"pdf-bytes")
    assert list(tmp_path.iterdir()) == []


def test_query_string_stays_out_of_the_name_and_type(tmp_path, monkeypatch):
    # os.path.basename() on the whole URL kept the query string, so the suffix
    # was ".pdf?token=secret" and file_type silently fell back to 'stream'.
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse()
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            _channel()._upload_file_url(f"{FILE_URL}?token=secret", "token")

    assert post.calls[0]["data"] == {"file_type": "pdf", "file_name": "report.pdf"}


def test_failed_download_returns_none_and_uploads_nothing(tmp_path, monkeypatch):
    # The caller checks the return value (`if not file_key: logger.warning(...)`),
    # so a non-200 has to arrive as None.
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse(status_code=404, content=b"<html>404</html>")
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
            result = _channel()._upload_file_url(FILE_URL, "token")

    assert result is None
    assert post.calls == []
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
            result = _channel()._upload_file_url(FILE_URL, "token")

    assert result is None


@pytest.mark.parametrize("failure", [RuntimeError("connection reset"), OSError("broken pipe")])
def test_upload_failure_leaves_nothing_behind(tmp_path, monkeypatch, failure):
    monkeypatch.chdir(tmp_path)
    response = DownloadResponse()

    with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
        with patch("channel.feishu.feishu_channel.requests.post", side_effect=failure):
            # The HTTP branch wraps its own body, so the failure is reported as
            # None rather than raised at the caller.
            result = _channel()._upload_file_url(FILE_URL, "token")

    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_file_stream_over_limit_is_not_uploaded(monkeypatch):
    response = DownloadResponse(content=b"oversize")
    post = _ok_upload()

    with patch("channel.feishu.feishu_channel.MAX_FILE_BYTES", 4):
        with patch("channel.feishu.feishu_channel.requests.get", return_value=response):
            with patch("channel.feishu.feishu_channel.requests.post", side_effect=post):
                result = _channel()._upload_file_url(FILE_URL, "token")

    assert result is None
    assert post.calls == []
    assert response.closed
