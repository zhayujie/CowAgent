# encoding:utf-8
"""
Regression tests for ``channel/wechat_kf/wechat_kf_channel.py::send``.

The agent bridge delivers local files as ``file://`` URLs
(``bridge/agent_bridge.py::_create_file_reply``). The previous code fed
those straight into ``requests.get`` (IMAGE_URL / VIDEO_URL) or ``open()``
(FILE), so a local-file reply raised ``InvalidSchema`` / ``FileNotFoundError``
and never reached the user. A FILE reply also dropped its accompanying
``text_content`` description.

These tests drive ``send()`` with a fake client (no network, no real
credentials) the same way ``tests/test_wechat_media_download_timeout.py``
does for the sibling channels.
"""
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import Reply, ReplyType
from channel.wechat_kf.wechat_kf_channel import WechatKfChannel


class _Ctx(dict):
    """Minimal Context stand-in: dict access plus the ``kwargs`` attribute
    that ``send()`` reads via ``context.kwargs.get("msg")``."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.kwargs = {}


def _channel():
    """The channel with just what ``send()`` touches, no ``__init__``.

    ``@singleton`` exposes the undecorated class as ``__wrapped__``;
    ``__init__`` would need real WeChat credentials.
    """
    cls = WechatKfChannel.__wrapped__
    channel = cls.__new__(cls)
    channel.client = MagicMock()
    channel.client.media.upload.return_value = {"media_id": "media-1"}
    return channel


def _ctx():
    return _Ctx(
        {"receiver": "user-1", "external_userid": "ext-1", "open_kfid": "kf-1"}
    )


class TestWechatKfImageUrlFileScheme(unittest.TestCase):
    def test_image_url_file_scheme_reads_from_disk(self):
        """A ``file://`` IMAGE_URL must be read from disk, never fetched."""
        channel = _channel()
        pic = Path(__file__).with_suffix(".png")  # any file works as bytes
        pic.write_bytes(b"\x89PNG\r\n\x1a\n fake-png-bytes")
        reply = Reply(ReplyType.IMAGE_URL, "file://{}".format(pic))
        ctx = _ctx()

        # If the code still calls requests.get on the file:// URL it must blow
        # up loudly here -- that is exactly the old InvalidSchema bug.
        with patch(
            "channel.wechat_kf.wechat_kf_channel.requests.get",
            side_effect=AssertionError("requests.get must not be called for file://"),
        ):
            channel.send(reply, ctx)

        pic.unlink()
        channel.client.media.upload.assert_called_once()
        args = channel.client.media.upload.call_args.args
        self.assertEqual(args[0], "image")
        self.assertIsInstance(args[1], io.BytesIO)

    def test_image_url_http_still_downloaded(self):
        """Regression: a genuine http(s) URL still hits the network."""
        channel = _channel()
        response = MagicMock()
        response.content = b"remote-bytes"
        reply = Reply(ReplyType.IMAGE_URL, "https://example.com/pic.png")
        ctx = _ctx()

        with patch(
            "channel.wechat_kf.wechat_kf_channel.requests.get", return_value=response
        ) as get:
            channel.send(reply, ctx)

        assert get.call_args.args == ("https://example.com/pic.png",)
        channel.client.media.upload.assert_called_once()


class TestWechatKfFileReply(unittest.TestCase):
    def test_file_reply_file_scheme_opens_local_path(self):
        """A ``file://`` FILE reply must open the local file, not ``file://...``."""
        channel = _channel()
        payload = Path(__file__).with_suffix(".bin")
        payload.write_bytes(b"report-bytes")
        reply = Reply(ReplyType.FILE, "file://{}".format(payload))
        ctx = _ctx()

        # open() on the raw file:// string is the old FileNotFoundError bug.
        real_open = open
        with patch(
            "channel.wechat_kf.wechat_kf_channel.open",
            side_effect=lambda p, *a, **k: (
                AssertionError("open called with file:// path") if str(p).startswith("file://") else real_open(p, *a, **k)
            ),
        ):
            channel.send(reply, ctx)

        payload.unlink()
        channel.client.media.upload.assert_called_once()
        args = channel.client.media.upload.call_args.args
        self.assertEqual(args[0], "file")
        self.assertEqual(args[1][0], payload.name)
        self.assertEqual(args[1][1], b"report-bytes")

    def test_file_reply_delivers_text_content(self):
        """The agent's file summary (text_content) must reach the user."""
        channel = _channel()
        sent_texts = []
        channel._send_text = lambda *a, **k: sent_texts.append(a)
        payload = Path(__file__).with_suffix(".bin")
        payload.write_bytes(b"report-bytes")
        reply = Reply(ReplyType.FILE, "file://{}".format(payload))
        reply.text_content = "今日报告已生成：12 条告警，3 条待处理。"
        ctx = _ctx()

        channel.send(reply, ctx)

        payload.unlink()
        channel.client.media.upload.assert_called_once()
        self.assertEqual(len(sent_texts), 1)
        # _send_text(self, external_userid, open_kfid, content)
        self.assertEqual(sent_texts[0][2], "今日报告已生成：12 条告警，3 条待处理。")


if __name__ == "__main__":
    unittest.main()
