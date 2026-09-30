# encoding:utf-8
"""
Regression tests for ``voice/linkai/linkai_voice.py``.

When LinkAI ASR/TTS fails, the old code returned ``None``. Every sibling
provider (ali, openai, mimo) returns a ``Reply(ReplyType.ERROR, ...)``
instead, so the user gets a failure message; LinkAI's ``None`` means the
bridge returns no Reply at all (``bridge/bridge.py::fetch_voice_to_text``)
and the turn goes silent. These tests assert the four failure exits now
produce an ERROR reply.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.linkai.linkai_voice import LinkAIVoice


class TestLinkAIVoiceErrorReply(unittest.TestCase):
    def _voice(self):
        return LinkAIVoice()

    def _audio(self):
        p = Path(__file__).with_suffix(".mp3")
        p.write_bytes(b"fake-audio-bytes")
        return p

    def test_voiceToText_http_error_returns_error_reply(self):
        v = self._voice()
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = {"message": "boom"}
        audio = self._audio()
        with patch("voice.linkai.linkai_voice.requests.post", return_value=resp):
            reply = v.voiceToText(str(audio))
        audio.unlink()
        self.assertIsNotNone(reply)
        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertIn("识别", reply.content)

    def test_voiceToText_exception_returns_error_reply(self):
        v = self._voice()
        audio = self._audio()
        with patch(
            "voice.linkai.linkai_voice.requests.post", side_effect=RuntimeError("net down")
        ):
            reply = v.voiceToText(str(audio))
        audio.unlink()
        self.assertIsNotNone(reply)
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_textToVoice_http_error_returns_error_reply(self):
        v = self._voice()
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = {"message": "boom"}
        with patch("voice.linkai.linkai_voice.requests.post", return_value=resp):
            reply = v.textToVoice("hello")
        self.assertIsNotNone(reply)
        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertIn("合成", reply.content)

    def test_textToVoice_exception_returns_error_reply(self):
        v = self._voice()
        with patch(
            "voice.linkai.linkai_voice.requests.post", side_effect=RuntimeError("net down")
        ):
            reply = v.textToVoice("hello")
        self.assertIsNotNone(reply)
        self.assertEqual(reply.type, ReplyType.ERROR)


if __name__ == "__main__":
    unittest.main()
