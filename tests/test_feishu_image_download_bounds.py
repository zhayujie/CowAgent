"""Feishu image events must not accept unbounded or partial downloads."""

import json
from pathlib import Path

from channel.feishu import feishu_message
from common import media_download


class FakeResponse:
    def __init__(self, chunks, status_code=200, headers=None):
        self.chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield from self.chunks


def _event(message_type, content):
    return {
        "app_id": "bot",
        "sender": {"sender_id": {"open_id": "user"}},
        "message": {
            "message_id": "message-1",
            "chat_id": "chat-1",
            "message_type": message_type,
            "content": json.dumps(content),
        },
    }


def _serve(monkeypatch, response):
    calls = []

    def get(url, **kwargs):
        calls.append(dict(kwargs, url=url))
        return response

    monkeypatch.setattr(media_download.requests, "get", get)
    return calls


def test_large_single_image_is_rejected_without_leaving_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(feishu_message, "MAX_IMAGE_BYTES", 5)
    response = FakeResponse([b"abc", b"def"])
    _serve(monkeypatch, response)

    message = feishu_message.FeishuMessage(
        _event("image", {"image_key": "image-1"}), access_token="tenant-token"
    )

    assert message.image_path is None
    assert "下载失败" in message.content
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_failed_post_image_is_marked_without_a_path(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(feishu_message, "MAX_IMAGE_BYTES", 5)
    response = FakeResponse([b"abcdef"], headers={"Content-Length": "6"})
    _serve(monkeypatch, response)

    post = {"content": [[{"tag": "text", "text": "hello"}, {"tag": "img", "image_key": "image-1"}]]}
    message = feishu_message.FeishuMessage(_event("post", post), access_token="tenant-token")

    assert message.content == "hello\n[图片下载失败: image-1]"
    assert message.image_paths == {}
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_small_image_streams_to_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    response = FakeResponse([b"abc", b"de"])
    calls = _serve(monkeypatch, response)

    message = feishu_message.FeishuMessage(
        _event("image", {"image_key": "image-1"}), access_token="tenant-token"
    )

    assert Path(message.image_path).read_bytes() == b"abcde"
    assert calls[0]["url"].endswith("/messages/message-1/resources/image-1")
    assert calls[0]["params"] == {"type": "image"}
    assert calls[0]["headers"] == {"Authorization": "Bearer tenant-token"}
    assert calls[0]["stream"] is True
    assert calls[0]["timeout"] == (5, 30)
    assert response.closed


def test_post_uses_each_successful_image_once(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    response = FakeResponse([b"image-bytes"])
    calls = _serve(monkeypatch, response)

    post = {"content": [[{"tag": "img", "image_key": "image-1"}, {"tag": "img", "image_key": "image-1"}]]}
    message = feishu_message.FeishuMessage(_event("post", post), access_token="tenant-token")

    assert len(calls) == 1
    assert list(message.image_paths) == ["image-1"]
    assert message.content.count("[图片:") == 1
    assert Path(message.image_paths["image-1"]).read_bytes() == b"image-bytes"


def test_interrupted_image_stream_cleans_up_partial_file(tmp_path, monkeypatch):
    class InterruptedResponse(FakeResponse):
        def iter_content(self, chunk_size):
            yield b"partial"
            raise OSError("connection lost")

    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    response = InterruptedResponse([b"partial"])
    _serve(monkeypatch, response)

    message = feishu_message.FeishuMessage(
        _event("image", {"image_key": "image-1"}), access_token="tenant-token"
    )

    assert message.image_path is None
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_image_key_cannot_escape_tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    _serve(monkeypatch, FakeResponse([b"png"]))

    message = feishu_message.FeishuMessage(
        _event("image", {"image_key": "../../evil"}), access_token="tenant-token"
    )

    assert Path(message.image_path).parent == tmp_path
