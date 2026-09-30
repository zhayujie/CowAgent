from unittest.mock import Mock

import pytest
import requests

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.wechat_kf import wechat_kf_channel


class FakeResponse:
    def __init__(self, chunks, *, status_code=200, headers=None):
        self.chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    @property
    def content(self):
        raise AssertionError("video download must stream instead of buffering .content")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield from self.chunks

    def close(self):
        self.closed = True


def send_media(reply_type, response, monkeypatch):
    channel_class = wechat_kf_channel.WechatKfChannel.__wrapped__
    channel = channel_class.__new__(channel_class)
    channel.client = Mock()
    channel.client.media.upload.return_value = {"media_id": "MEDIA-1"}
    channel._send_image = Mock()
    channel._send_video = Mock()
    monkeypatch.setattr(wechat_kf_channel.requests, "get", lambda *args, **kwargs: response)
    context = Context(
        ContextType.TEXT,
        kwargs={"receiver": "u1", "external_userid": "ext1", "open_kfid": "kf1"},
    )
    channel.send(Reply(reply_type, "https://example.com/media"), context)
    return channel


@pytest.mark.parametrize("reply_type", [ReplyType.IMAGE_URL, ReplyType.VIDEO_URL])
def test_oversized_remote_media_is_not_uploaded(reply_type, monkeypatch):
    response = FakeResponse([], headers={"Content-Length": str(20 * 1024 * 1024 + 1)})

    channel = send_media(reply_type, response, monkeypatch)

    assert response.closed
    channel.client.media.upload.assert_not_called()
    channel._send_image.assert_not_called()
    channel._send_video.assert_not_called()


def test_video_stream_without_content_length_stops_at_limit(monkeypatch):
    response = FakeResponse([b"x" * (10 * 1024 * 1024 + 1)])

    channel = send_media(ReplyType.VIDEO_URL, response, monkeypatch)

    assert response.closed
    channel.client.media.upload.assert_not_called()


@pytest.mark.parametrize("reply_type", [ReplyType.IMAGE_URL, ReplyType.VIDEO_URL])
def test_http_error_body_is_not_uploaded(reply_type, monkeypatch):
    response = FakeResponse([b"not found"], status_code=404)

    channel = send_media(reply_type, response, monkeypatch)

    assert response.closed
    channel.client.media.upload.assert_not_called()


def test_broken_image_stream_is_closed_without_upload(monkeypatch):
    response = FakeResponse([])

    def fail_stream(*_args, **_kwargs):
        raise requests.ConnectionError("connection lost")

    response.iter_content = fail_stream

    channel = send_media(ReplyType.IMAGE_URL, response, monkeypatch)

    assert response.closed
    channel.client.media.upload.assert_not_called()


def test_video_is_streamed_and_response_closed(monkeypatch):
    response = FakeResponse([b"video", b" payload"])

    channel = send_media(ReplyType.VIDEO_URL, response, monkeypatch)

    media_type, stream = channel.client.media.upload.call_args.args
    assert media_type == "video"
    assert stream.read() == b"video payload"
    assert response.closed
    channel._send_video.assert_called_once_with("ext1", "kf1", "MEDIA-1")


def test_image_response_is_closed_after_successful_upload(monkeypatch):
    response = FakeResponse([b"image payload"])

    channel = send_media(ReplyType.IMAGE_URL, response, monkeypatch)

    media_type, stream = channel.client.media.upload.call_args.args
    assert media_type == "image"
    assert stream.read() == b"image payload"
    assert response.closed
    channel._send_image.assert_called_once_with("ext1", "kf1", "MEDIA-1")
