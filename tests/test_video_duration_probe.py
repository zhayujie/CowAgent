# encoding:utf-8
"""Video duration probing, shared by DingTalk and Feishu.

DingTalk's sampleVideo message needs the clip duration in seconds. Both
channels probe it with ffprobe through common.media_duration, which answers 0
on failure so each caller keeps its own fallback (DingTalk: 30s, Feishu: 0).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.media_duration import get_video_duration_ms


class _Probe:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, "boom"


class TestGetVideoDurationMs(unittest.TestCase):

    def test_a_clean_probe_answer_is_converted_to_milliseconds(self):
        with patch("common.media_duration.subprocess.run", return_value=_Probe("12.345")):
            self.assertEqual(get_video_duration_ms("clip.mp4"), 12345)

    def test_a_failed_probe_answers_zero(self):
        with patch("common.media_duration.subprocess.run", return_value=_Probe("", returncode=1)):
            self.assertEqual(get_video_duration_ms("clip.mp4"), 0)

    def test_a_missing_ffprobe_answers_zero(self):
        with patch("common.media_duration.subprocess.run", side_effect=FileNotFoundError()):
            self.assertEqual(get_video_duration_ms("clip.mp4"), 0)


class TestDingTalkUsesTheProbe(unittest.TestCase):

    def test_the_video_message_carries_the_probed_duration(self):
        from types import SimpleNamespace

        from channel.dingtalk import dingtalk_channel as mod

        cls = mod.DingTalkChanel.__wrapped__
        ch = cls.__new__(cls)
        sent = []
        ch.get_access_token = lambda: "tok"
        ch.upload_media = lambda path, media_type: "media-1"
        ch._send_file_message = lambda *a, **k: sent.append(a[3]) or True
        ch.reply_text = lambda *a, **k: None
        ch._robot_code = "robot-1"
        ch.cfg = lambda key, default=None: default

        from bridge.context import Context, ContextType
        from bridge.reply import Reply, ReplyType

        context = Context(ContextType.TEXT, "hello")
        context["receiver"] = "user-1"
        context["isgroup"] = False
        # A real message rides in msg; the video branch only needs its
        # is_group flag and the wrapped incoming_message.
        incoming = SimpleNamespace()
        context["msg"] = SimpleNamespace(is_group=False, incoming_message=incoming,
                                         robot_code="robot-1")

        def _send(path, probed_ms):
            reply = Reply(ReplyType.VIDEO, path)
            with patch.object(mod, "get_video_duration_ms", lambda p: probed_ms):
                ch.send(reply, context)
            return sent.pop()

        # The unit is seconds: a 95s clip reports "95", not 95000.
        self.assertEqual(_send(os.devnull, 95000)["duration"], "95")
        # Sub-second clips round up to at least 1s rather than reporting "0".
        self.assertEqual(_send(os.devnull, 400)["duration"], "1")
        # A failed probe keeps the legacy 30s fallback.
        self.assertEqual(_send(os.devnull, 0)["duration"], "30")
        # Remote URLs are not probed at all (ffprobe must not fetch them).
        self.assertEqual(_send("https://cdn.example.com/clip.mp4", 95000)["duration"], "30")


if __name__ == "__main__":
    unittest.main()
