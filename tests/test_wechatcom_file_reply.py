"""A file or video reply must reach a WeCom-app user instead of vanishing.

``WechatComAppChannel.send`` (channel/wechatcom/wechatcomapp_channel.py:92)
handled text, voice and images only: a FILE or VIDEO reply matched no branch
and fell off the end of the method, so the agent's answer was dropped without
so much as a log line. Every other channel delivers files -- wechat_kf:249,
qq:578, weixin:822, wecom_bot:997, dingtalk:919, feishu:907, discord:479,
slack:487, telegram:704 -- and this one declares ``NOT_SUPPORT_REPLYTYPE = []``,
so nothing downgrades the reply to text before it gets here either.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.wechatcom import wechatcomapp_channel as channel_module


class _Recorder:
    """Stands in for ``client.media`` and ``client.message``, recording calls."""

    def __init__(self):
        self.calls = []
        self.media = self
        self.message = self

    def upload(self, media_type, media_file):
        # A file reply hands over ``(name, body)``; an image hands over the
        # BytesIO that goes straight to the upload API.
        if isinstance(media_file, tuple):
            name, body = media_file
        else:
            name, body = None, media_file.read()
        self.calls.append(("upload", media_type, name, body))
        return {"media_id": "media-1"}

    def send_text(self, agent_id, receiver, text):
        self.calls.append(("text", text))

    def send_file(self, agent_id, receiver, media_id):
        self.calls.append(("file", media_id))

    def send_image(self, agent_id, receiver, media_id):
        self.calls.append(("image", media_id))

    def send_video(self, agent_id, receiver, media_id):
        self.calls.append(("video", media_id))


class WeComAppFileReplyTest(unittest.TestCase):
    def setUp(self):
        self.rec = _Recorder()
        # __wrapped__ is the undecorated class (@singleton hands out a factory
        # function); __new__ skips __init__, which needs live credentials.
        cls = channel_module.WechatComAppChannel.__wrapped__
        self.channel = cls.__new__(cls)
        self.channel.agent_id = "1000002"
        self.channel.client = self.rec
        self.context = Context()
        self.context["receiver"] = "user-1"

    @staticmethod
    def _local_file():
        fd, path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"report-body")
        return path

    def test_file_reply_is_uploaded_and_delivered(self):
        """The document the agent produced actually reaches the user."""
        path = self._local_file()
        reply = Reply(ReplyType.FILE, "file://" + path)
        reply.file_name = "weekly.pdf"
        self.channel.send(reply, self.context)
        self.assertIn(("upload", "file", "weekly.pdf", b"report-body"), self.rec.calls)
        self.assertIn(("file", "media-1"), self.rec.calls)

    def test_video_reply_goes_out_as_a_video(self):
        path = self._local_file()
        reply = Reply(ReplyType.FILE, "file://" + path)
        reply.file_type = "video"
        self.channel.send(reply, self.context)
        self.assertIn(
            ("upload", "video", os.path.basename(path), b"report-body"), self.rec.calls
        )
        self.assertIn(("video", "media-1"), self.rec.calls)

    def test_the_agents_note_is_sent_before_the_file(self):
        """A file reply carries its prose in text_content; it must not be lost."""
        reply = Reply(ReplyType.FILE, "file://" + self._local_file())
        reply.text_content = "这是本周报告"
        self.channel.send(reply, self.context)
        self.assertEqual(["text", "upload", "file"], [c[0] for c in self.rec.calls])
        self.assertEqual("这是本周报告", self.rec.calls[0][1])

    def test_a_remote_file_url_is_downloaded_before_uploading(self):
        with patch("common.media_download.requests.get") as get:
            get.return_value.headers = {}
            get.return_value.iter_content.return_value = [b"remote-body"]
            reply = Reply(ReplyType.FILE, "https://files.example.com/weekly.pdf")
            reply.file_name = "weekly.pdf"
            self.channel.send(reply, self.context)
        self.assertIn(("upload", "file", "weekly.pdf", b"remote-body"), self.rec.calls)
        self.assertTrue(get.call_args.kwargs["stream"])

    def test_a_signed_url_keeps_its_real_extension(self):
        with patch("common.media_download.requests.get") as get:
            get.return_value.headers = {}
            get.return_value.iter_content.return_value = [b"remote-body"]
            self.channel.send(
                Reply(ReplyType.FILE, "https://files.example.com/weekly.pdf?sig=a/b"), self.context
            )
        uploads = [c for c in self.rec.calls if c[0] == "upload"]
        self.assertEqual(1, len(uploads))
        self.assertTrue(uploads[0][2].endswith(".pdf"))

    def test_a_missing_file_reports_instead_of_uploading(self):
        self.channel.send(Reply(ReplyType.FILE, "file:///nonexistent/x.pdf"), self.context)
        self.assertEqual([], [c for c in self.rec.calls if c[0] == "upload"])
        self.assertTrue(any(c[0] == "text" for c in self.rec.calls))

    def test_an_unhandled_reply_type_falls_back_to_text(self):
        self.channel.send(Reply(ReplyType.CARD, "card-payload"), self.context)
        self.assertIn(("text", "card-payload"), self.rec.calls)

    @staticmethod
    def _local_image():
        fd, path = tempfile.mkstemp(suffix=".png")
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"\x89png-body")
        return path

    def test_a_local_image_reply_is_uploaded_and_delivered(self):
        """An image the agent wrote on disk reaches the user.

        ``bridge/agent_bridge.py:1902-1908`` and ``channel/chat_channel.py:422``
        both hand a generated image over as ``Reply(ReplyType.IMAGE_URL,
        "file://<path>")``, but this branch only knew how to fetch a URL:
        ``download_bytes`` has no ``file://`` adapter, so the upload never ran
        and the user got the prose with the image missing.
        """
        path = self._local_image()
        self.channel.send(Reply(ReplyType.IMAGE_URL, "file://" + path), self.context)
        self.assertIn(("upload", "image", None, b"\x89png-body"), self.rec.calls)
        self.assertIn(("image", "media-1"), self.rec.calls)

    def test_a_local_image_path_without_a_scheme_is_uploaded_too(self):
        path = self._local_image()
        self.channel.send(Reply(ReplyType.IMAGE_URL, path), self.context)
        self.assertIn(("upload", "image", None, b"\x89png-body"), self.rec.calls)
        self.assertIn(("image", "media-1"), self.rec.calls)

    def test_a_remote_image_is_still_downloaded_before_uploading(self):
        """Reading local files must not take the network path away."""
        with patch("common.media_download.requests.get") as get:
            get.return_value.headers = {}
            get.return_value.iter_content.return_value = [b"remote-png"]
            self.channel.send(
                Reply(ReplyType.IMAGE_URL, "https://img.example.com/a.png"), self.context
            )
        self.assertIn(("upload", "image", None, b"remote-png"), self.rec.calls)
        self.assertIn(("image", "media-1"), self.rec.calls)
        self.assertTrue(get.call_args.kwargs["stream"])

