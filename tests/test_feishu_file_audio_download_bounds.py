"""Feishu file and voice downloads must be complete before they are exposed."""

import json

from channel.feishu.feishu_message import FeishuMessage
from common import media_download


class Response:
    def __init__(self, body=b"media", headers=None, fail=False):
        self.status_code = 200
        self.headers = headers or {}
        self.body = body
        self.fail = fail
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body
        if self.fail:
            raise OSError("connection lost")

    def close(self):
        self.closed = True


def _message(kind, file_key="file_v2_key"):
    content = {"file_key": file_key}
    if kind == "file":
        content["file_name"] = "report.pdf"
    return {
        "app_id": "cli_bot",
        "sender": {"sender_id": {"open_id": "ou_user"}},
        "message": {
            "message_id": "om_child",
            "chat_id": "oc_chat",
            "message_type": kind,
            "content": json.dumps(content),
        },
    }


def test_file_download_is_streamed_and_published(monkeypatch, tmp_path):
    monkeypatch.setattr("channel.feishu.feishu_message.state_dir.tmp_dir", lambda: tmp_path)
    response = Response(body=b"%PDF-1.4")
    calls = []

    def get(url, **kwargs):
        calls.append(dict(kwargs, url=url))
        return response

    monkeypatch.setattr(media_download.requests, "get", get)
    message = FeishuMessage(_message("file"), access_token="token")
    message.prepare()

    assert (tmp_path / "file_v2_key.pdf").read_bytes() == b"%PDF-1.4"
    assert message.content == str(tmp_path / "file_v2_key.pdf")
    assert calls[0]["url"].endswith("/messages/om_child/resources/file_v2_key")
    assert calls[0]["params"] == {"type": "file"}
    assert calls[0]["stream"] is True
    assert calls[0]["timeout"] == (5, 30)
    assert response.closed


def test_declared_oversize_file_leaves_no_path(monkeypatch, tmp_path):
    monkeypatch.setattr("channel.feishu.feishu_message.state_dir.tmp_dir", lambda: tmp_path)
    response = Response(headers={"Content-Length": str(media_download.MAX_FILE_BYTES + 1)})
    monkeypatch.setattr(media_download.requests, "get", lambda url, **kwargs: response)

    message = FeishuMessage(_message("file"), access_token="token")
    message.prepare()

    assert not (tmp_path / "file_v2_key.pdf").exists()
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_voice_stream_overflow_preserves_existing_file(monkeypatch, tmp_path):
    monkeypatch.setattr("channel.feishu.feishu_message.state_dir.tmp_dir", lambda: tmp_path)
    monkeypatch.setattr("channel.feishu.feishu_message.MAX_FILE_BYTES", 4)
    destination = tmp_path / "file_v2_key.opus"
    destination.write_bytes(b"previous voice")
    response = Response(body=b"new voice")
    monkeypatch.setattr(media_download.requests, "get", lambda url, **kwargs: response)

    message = FeishuMessage(_message("audio"), access_token="token")
    message.prepare()

    assert destination.read_bytes() == b"previous voice"
    assert list(tmp_path.iterdir()) == [destination]
    assert response.closed


def test_interrupted_file_stream_leaves_no_partial_file(monkeypatch, tmp_path):
    monkeypatch.setattr("channel.feishu.feishu_message.state_dir.tmp_dir", lambda: tmp_path)
    response = Response(fail=True)
    monkeypatch.setattr(media_download.requests, "get", lambda url, **kwargs: response)

    message = FeishuMessage(_message("file", "../evil"), access_token="token")
    message.prepare()

    assert message.content.startswith(str(tmp_path))
    assert list(tmp_path.iterdir()) == []
    assert response.closed
