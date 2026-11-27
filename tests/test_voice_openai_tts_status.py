# encoding:utf-8
"""
A failed OpenAI synthesis must answer with an ERROR reply, not an audio file.

``OpenaiVoice.textToVoice`` never inspected ``response.status_code``, so on a
401/429/5xx OpenAI's JSON error envelope was written verbatim into a file named
``*.mp3`` and returned as a *successful* ``ReplyType.VOICE`` -- the user got a
voice bubble that silently refuses to play while the log says
``text_to_Voice success``.

Every sibling already checks: ``voice/custom/custom_voice.py`` checks it before
building the file name, ``voice/mimo/mimo_voice.py`` and ``voice/linkai`` return
an ERROR reply, and ``OpenaiVoice.voiceToText`` in this very module does both.
These tests pin the missing check, and pin that a failed request leaves no junk
``.mp3`` behind.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.openai.openai_voice import OpenaiVoice

# The same message voiceToText's except-branch and the custom/mimo/linkai
# backends use for "synthesis did not happen".
TTS_FAILED = "遇到了一点小问题，请稍后再问我吧"

ERROR_BODY = b'{"error":{"message":"Incorrect API key provided"}}'


def _conf(**values):
    """config.conf() returning the provided dict, ``None`` for missing keys."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: values.get(key, default))
    return MagicMock(return_value=cfg)


def _failed_response(status_code):
    """What OpenAI actually returns on a failed /audio/speech call."""
    response = MagicMock()
    response.status_code = status_code
    response.content = ERROR_BODY
    response.text = ERROR_BODY.decode()
    return response


class TestOpenaiVoiceTtsStatusCheck(unittest.TestCase):
    def _synthesize(self, response, tmp):
        """Run textToVoice with the tmp dir pointed at ``tmp`` (a real dir)."""
        voice = OpenaiVoice()
        with patch("voice.openai.openai_voice.conf",
                   _conf(open_ai_api_key="sk-test", text_to_voice_model="tts-1")):
            with patch("voice.openai.openai_voice.requests.post", return_value=response):
                with patch("voice.openai.openai_voice.TmpDir") as tmp_dir:
                    tmp_dir.return_value.path.return_value = tmp + os.sep
                    return voice.textToVoice("hello")

    def test_a_failed_synthesis_returns_an_error_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            reply = self._synthesize(_failed_response(401), tmp)

        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertEqual(reply.content, TTS_FAILED)

    def test_a_server_error_is_reported_rather_than_written_as_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            reply = self._synthesize(_failed_response(500), tmp)

        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertEqual(reply.content, TTS_FAILED)

    def test_a_failed_synthesis_leaves_no_audio_file_behind(self):
        """The error envelope must never be persisted under a *.mp3 name."""
        with tempfile.TemporaryDirectory() as tmp:
            self._synthesize(_failed_response(401), tmp)
            leftovers = os.listdir(tmp)

        self.assertEqual(leftovers, [], f"failed synthesis left {leftovers}")

    def test_the_status_code_is_logged_for_the_failure(self):
        """A 401 with no logged status is undiagnosable in a bug report."""
        response = _failed_response(401)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("voice.openai.openai_voice.logger") as log:
                self._synthesize(response, tmp)

        logged = " ".join(str(call) for call in log.error.call_args_list)
        self.assertIn("401", logged)
        self.assertIn("Incorrect API key", logged)

    def test_a_successful_synthesis_still_returns_a_voice_reply(self):
        response = MagicMock()
        response.status_code = 200
        # TTS bodies are streamed now, so the stub has to answer `iter_content`.
        response.iter_content.return_value = [b"mp3-bytes"]

        with tempfile.TemporaryDirectory() as tmp:
            reply = self._synthesize(response, tmp)

            self.assertEqual(reply.type, ReplyType.VOICE)
            self.assertEqual(os.path.dirname(reply.content), tmp)
            written = os.listdir(tmp)
            self.assertEqual(len(written), 1)
            self.assertTrue(written[0].endswith(".mp3"))
            with open(reply.content, "rb") as f:
                self.assertEqual(f.read(), b"mp3-bytes")


if __name__ == "__main__":
    unittest.main()
