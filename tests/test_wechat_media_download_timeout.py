# encoding:utf-8
"""
Unit tests for the WeChat-family channels' outbound media downloads.

``channel/wechatmp``, ``channel/wechat_kf`` and ``channel/wechatcom`` fetch
``ReplyType.IMAGE_URL`` / ``VIDEO_URL`` media with ``requests.get(..., stream=True)``
and then iterate the body. Without a timeout a stalled file host leaves the
channel's send path blocked forever, so the user never gets an answer. The
sibling channels already bound the same downloads (``slack_channel.py`` and
``dingtalk_message.py`` use ``timeout=60``); these did not.
"""
import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import Reply, ReplyType
from channel.wechatcom.wechatcomapp_channel import WechatComAppChannel

WECHAT_CHANNEL_MODULES = (
    "channel/wechatmp/wechatmp_channel.py",
    "channel/wechat_kf/wechat_kf_channel.py",
    "channel/wechatcom/wechatcomapp_channel.py",
)


class TestWechatComAppImageDownload(unittest.TestCase):
    @staticmethod
    def _channel():
        """The channel with just what send() touches, no startup().

        The class is wrapped by @singleton, which exposes the undecorated class
        as __wrapped__; __init__ would need real channel credentials.
        """
        cls = WechatComAppChannel.__wrapped__
        channel = cls.__new__(cls)
        channel.agent_id = "agent-1"
        channel.client = MagicMock()
        channel.client.media.upload.return_value = {"media_id": "media-1"}
        return channel

    def test_image_url_download_is_bounded(self):
        response = MagicMock()
        response.headers = {}
        response.iter_content.return_value = [b"png-bytes"]
        channel = self._channel()

        with patch(
            "common.media_download.requests.get", return_value=response
        ) as get:
            channel.send(
                Reply(ReplyType.IMAGE_URL, "https://example.com/pic.png"),
                {"receiver": "user-1"},
            )

        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], "https://example.com/pic.png")
        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertEqual(get.call_args.kwargs["timeout"], 60)
        response.close.assert_called_once()

    def test_oversized_image_is_not_uploaded(self):
        response = MagicMock()
        response.headers = {"Content-Length": str(20 * 1024 * 1024 + 1)}
        channel = self._channel()

        with patch("common.media_download.requests.get", return_value=response):
            channel.send(Reply(ReplyType.IMAGE_URL, "https://example.com/huge.png"), {"receiver": "user-1"})

        response.iter_content.assert_not_called()
        response.close.assert_called_once()
        channel.client.media.upload.assert_not_called()

    def test_streamed_overflow_is_not_uploaded(self):
        response = MagicMock()
        response.headers = {}
        response.iter_content.return_value = [b"small", b"overflow"]
        channel = self._channel()

        with patch("channel.wechatcom.wechatcomapp_channel.MAX_IMAGE_BYTES", 8), \
                patch("common.media_download.requests.get", return_value=response):
            channel.send(Reply(ReplyType.IMAGE_URL, "https://example.com/huge.png"), {"receiver": "user-1"})

        response.close.assert_called_once()
        channel.client.media.upload.assert_not_called()

    def test_http_error_body_is_not_uploaded(self):
        import requests

        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("404")
        channel = self._channel()

        with patch("common.media_download.requests.get", return_value=response):
            channel.send(Reply(ReplyType.IMAGE_URL, "https://example.com/missing.png"), {"receiver": "user-1"})

        response.close.assert_called_once()
        channel.client.media.upload.assert_not_called()


class TestWechatChannelsBoundEveryRequest(unittest.TestCase):
    def test_every_outbound_request_carries_a_timeout(self):
        """One unbounded download blocks a channel's send path forever.

        The call sites are inline branches of each ``send()``, so driving all of
        them would need a separate client harness per channel for one keyword.
        Walking the source covers every site at once -- including any added here
        later, which is the way this regresses.
        """
        root = Path(__file__).resolve().parent.parent
        unbounded = []
        for relative in WECHAT_CHANNEL_MODULES:
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "requests"
                ):
                    continue
                if not any(keyword.arg == "timeout" for keyword in node.keywords):
                    unbounded.append(f"{relative}:{node.lineno} {ast.unparse(node)}")

        self.assertEqual(unbounded, [])


if __name__ == "__main__":
    unittest.main()
