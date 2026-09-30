# encoding:utf-8
"""wechat_kf must upload a locally generated video instead of dropping it.

``ChatChannel`` hands an agent-produced video over as
``Reply(ReplyType.VIDEO, "file://" + path)``. ``send()`` dispatches
``VIDEO_URL`` but never ``VIDEO``, so the reply hit the trailing ``else`` and
was only logged as ``unsupported reply type``: the user received nothing at
all. Every other channel that dispatches ``VIDEO_URL`` also dispatches
``VIDEO`` (weixin / wechatcom / wechatmp / wecom_bot / qq), and the three that
shared this gap were fixed the same way (#3289 discord, slack/telegram).

``_read_media`` is the helper the FILE branch already uses: it reads a
``file://`` path from disk and size-caps a real http(s) download.
"""
import io
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import Reply, ReplyType
from channel.wechat_kf.wechat_kf_channel import WechatKfChannel


class _Ctx(dict):
    """``send()`` reads ``context.kwargs.get("msg")``; nothing else is touched."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.kwargs = {}


def _channel():
    """Only what ``send()`` needs: ``@singleton`` hides the class behind
    ``__wrapped__``, and ``__init__`` would need real WeChat credentials."""
    cls = WechatKfChannel.__wrapped__
    channel = cls.__new__(cls)
    channel.client = MagicMock()
    channel.client.media.upload.return_value = {"media_id": "media-1"}
    return channel


def _ctx():
    return _Ctx({"receiver": "user-1", "external_userid": "ext-1", "open_kfid": "kf-1"})


def test_local_video_reply_is_uploaded_from_disk():
    """A ``file://`` VIDEO reply is uploaded as a video, then sent."""
    channel = _channel()
    sent = []
    channel._send_video = lambda *a, **k: sent.append(a)
    clip = Path(__file__).with_suffix(".mp4")
    clip.write_bytes(b"fake-mp4-bytes")

    try:
        # requests.get cannot open a file:// path; it must not be tried.
        with patch(
            "channel.wechat_kf.wechat_kf_channel.requests.get",
            side_effect=AssertionError("requests.get must not run for file://"),
        ):
            channel.send(Reply(ReplyType.VIDEO, "file://{}".format(clip)), _ctx())
    finally:
        clip.unlink()

    media_type, payload = channel.client.media.upload.call_args.args
    assert media_type == "video"
    assert isinstance(payload, io.BytesIO)
    # _send_video(self, external_userid, open_kfid, media_id)
    assert sent == [("ext-1", "kf-1", "media-1")]


def test_video_url_reply_still_downloads_and_sends():
    """Regression: a remote VIDEO_URL keeps its existing behaviour."""
    channel = _channel()
    sent = []
    channel._send_video = lambda *a, **k: sent.append(a)

    with patch(
        "channel.wechat_kf.wechat_kf_channel.download_bytes",
        return_value=b"remote-mp4-bytes",
    ) as download:
        channel.send(Reply(ReplyType.VIDEO_URL, "https://example.com/clip.mp4"), _ctx())

    assert download.call_args.args[0] == "https://example.com/clip.mp4"
    assert channel.client.media.upload.call_args.args[0] == "video"
    assert sent == [("ext-1", "kf-1", "media-1")]
