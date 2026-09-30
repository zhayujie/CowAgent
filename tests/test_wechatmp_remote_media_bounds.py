from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from bridge.reply import Reply, ReplyType
from channel.wechatmp import wechatmp_channel
from common import media_download


class FakeResponse:
    def __init__(self, chunks, *, status_code=200, headers=None):
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


def make_channel(passive):
    channel = wechatmp_channel.WechatMPChannel.__wrapped__.__new__(
        wechatmp_channel.WechatMPChannel.__wrapped__
    )
    channel.passive_reply = passive
    channel.cache_dict = defaultdict(list)
    channel.client = Mock()
    channel.client.material.add.return_value = {"media_id": "MEDIA-1"}
    channel.client.media.upload.return_value = {"media_id": "MEDIA-1"}
    return channel


@pytest.mark.parametrize("passive", [True, False])
@pytest.mark.parametrize("reply_type", [ReplyType.IMAGE_URL, ReplyType.VIDEO_URL])
def test_remote_media_rejects_oversized_content_length_before_upload(
    monkeypatch, passive, reply_type
):
    response = FakeResponse([], headers={"Content-Length": str(10 * 1024 * 1024 + 1)})
    monkeypatch.setattr(wechatmp_channel.requests, "get", lambda *args, **kwargs: response)
    channel = make_channel(passive)

    channel.send(
        Reply(reply_type, "https://example.com/media"),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )

    assert response.closed
    channel.client.material.add.assert_not_called()
    channel.client.media.upload.assert_not_called()


def test_remote_media_enforces_limit_when_content_length_is_missing(monkeypatch):
    response = FakeResponse([b"x" * (10 * 1024 * 1024 + 1)])
    monkeypatch.setattr(wechatmp_channel.requests, "get", lambda *args, **kwargs: response)
    channel = make_channel(False)

    channel.send(
        Reply(ReplyType.VIDEO_URL, "https://example.com/large.mp4"),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )

    assert response.closed
    channel.client.media.upload.assert_not_called()


def test_remote_media_checks_http_status_and_does_not_upload_error_body(monkeypatch):
    response = FakeResponse([b"not found"], status_code=404)
    monkeypatch.setattr(wechatmp_channel.requests, "get", lambda *args, **kwargs: response)
    channel = make_channel(False)

    channel.send(
        Reply(ReplyType.IMAGE_URL, "https://example.com/missing.png"),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )

    assert response.closed
    channel.client.media.upload.assert_not_called()


def test_remote_media_request_uses_timeouts_and_handles_network_failure(monkeypatch):
    calls = []

    def fail_request(*args, **kwargs):
        calls.append(kwargs)
        raise requests.Timeout("download stalled")

    monkeypatch.setattr(wechatmp_channel.requests, "get", fail_request)
    channel = make_channel(False)

    channel.send(
        Reply(ReplyType.IMAGE_URL, "https://example.com/slow.png"),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )

    assert calls[0]["timeout"] == (5, 30)
    channel.client.media.upload.assert_not_called()


def test_remote_media_closes_response_when_stream_fails(monkeypatch):
    response = FakeResponse([])

    def fail_stream(*_args, **_kwargs):
        raise requests.ConnectionError("connection lost")

    response.iter_content = fail_stream
    monkeypatch.setattr(wechatmp_channel.requests, "get", lambda *args, **kwargs: response)
    channel = make_channel(True)

    channel.send(
        Reply(ReplyType.VIDEO_URL, "https://example.com/video.mp4"),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )

    assert response.closed
    channel.client.material.add.assert_not_called()


def test_remote_media_stops_a_slow_stream(monkeypatch):
    response = FakeResponse([b"partial"])
    monkeypatch.setattr(wechatmp_channel.requests, "get", lambda *args, **kwargs: response)
    times = iter([0, 61])
    monkeypatch.setattr(
        media_download,
        "time",
        SimpleNamespace(monotonic=lambda: next(times)),
    )
    channel = make_channel(False)

    channel.send(
        Reply(ReplyType.VIDEO_URL, "https://example.com/slow.mp4"),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )

    assert response.closed
    channel.client.media.upload.assert_not_called()


@pytest.mark.parametrize("passive", [True, False])
@pytest.mark.parametrize("reply_type", [ReplyType.IMAGE_URL, ReplyType.VIDEO_URL])
def test_remote_media_still_uploads_valid_payload(monkeypatch, passive, reply_type):
    payload = (
        b"\x89PNG\r\n\x1a\n" + b"payload"
        if reply_type == ReplyType.IMAGE_URL
        else b"video payload"
    )
    response = FakeResponse([payload])
    monkeypatch.setattr(wechatmp_channel.requests, "get", lambda *args, **kwargs: response)
    channel = make_channel(passive)

    channel.send(
        Reply(reply_type, "https://example.com/media"),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )

    uploader = channel.client.material.add if passive else channel.client.media.upload
    _, (_, stream, content_type) = uploader.call_args.args
    assert stream.read() == payload
    assert content_type == (
        "image/png" if reply_type == ReplyType.IMAGE_URL else "video/mp4"
    )
    assert response.closed
