# encoding:utf-8
"""
Unit tests for voice/openai/openai_voice.py request handling.

Covers:
  - the transcription upload handle is open while the request is in flight and
    closed by the time voiceToText returns (not left to the reference counter)
  - both outbound calls carry a timeout
  - a non-JSON error body (gateway HTML) is reported with its status code
    instead of being masked by the decode error

``voice/custom/custom_voice.py`` is the structural sibling of this module: it
speaks the same two OpenAI-compatible endpoints and already does all three.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.openai.openai_voice import OpenaiVoice


def _conf(**values):
    """config.conf() returning the provided dict, ``None`` for missing keys."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: values.get(key, default))
    return MagicMock(return_value=cfg)


def _assert_bounded(test, timeout):
    """A timeout must be a (connect, read) pair with both values positive."""
    test.assertIsInstance(timeout, tuple)
    connect, read = timeout
    test.assertGreater(connect, 0)
    test.assertGreater(read, 0)


class TestOpenaiVoice(unittest.TestCase):
    def test_voice_to_text_closes_the_upload_handle(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"text": "hello"}

        handles = []
        open_at_request = []

        def _post(url, **kwargs):
            handle = kwargs["files"]["file"]
            handles.append(handle)
            open_at_request.append(not handle.closed)
            return response

        voice = OpenaiVoice()
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "recording.webm")
            with open(audio, "wb") as f:
                f.write(b"audio-bytes")
            with patch("voice.openai.openai_voice.conf", _conf(open_ai_api_key="sk-test")):
                with patch("voice.openai.openai_voice.requests.post", side_effect=_post):
                    reply = voice.voiceToText(audio)

        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(reply.content, "hello")
        # Open while the upload is in flight — a closed handle would send nothing.
        self.assertEqual(open_at_request, [True])
        # And closed once voiceToText returns, rather than whenever the last
        # reference happens to go away.
        self.assertTrue(handles[0].closed)

    def test_voice_to_text_bounds_the_request(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"text": "hello"}

        voice = OpenaiVoice()
        with patch("voice.openai.openai_voice.conf", _conf(open_ai_api_key="sk-test")):
            with patch("voice.openai.openai_voice.requests.post", return_value=response) as post:
                with patch("builtins.open", mock_open(read_data=b"audio-bytes")):
                    voice.voiceToText("/fake/recording.webm")

        _assert_bounded(self, post.call_args.kwargs["timeout"])

    def test_text_to_voice_bounds_the_request(self):
        response = MagicMock()
        response.status_code = 200
        response.content = b"mp3-bytes"

        voice = OpenaiVoice()
        with patch("voice.openai.openai_voice.conf", _conf(open_ai_api_key="sk-test")):
            with patch("voice.openai.openai_voice.requests.post", return_value=response) as post:
                with patch("voice.openai.openai_voice.TmpDir") as tmp_dir:
                    tmp_dir.return_value.path.return_value = tempfile.gettempdir() + os.sep
                    with patch("builtins.open", mock_open()):
                        reply = voice.textToVoice("hello")

        self.assertEqual(reply.type, ReplyType.VOICE)
        _assert_bounded(self, post.call_args.kwargs["timeout"])

    def test_voice_to_text_reports_the_status_when_the_body_is_not_json(self):
        """A gateway error page must not hide the status code behind a decode error."""
        response = MagicMock()
        response.status_code = 502
        response.text = "<html>Bad Gateway</html>"
        response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

        voice = OpenaiVoice()
        with patch("voice.openai.openai_voice.conf", _conf(open_ai_api_key="sk-test")):
            with patch("voice.openai.openai_voice.requests.post", return_value=response):
                with patch("voice.openai.openai_voice.logger") as log:
                    with patch("builtins.open", mock_open(read_data=b"audio-bytes")):
                        reply = voice.voiceToText("/fake/recording.webm")

        self.assertEqual(reply.type, ReplyType.ERROR)
        logged = " ".join(str(call) for call in log.error.call_args_list)
        self.assertIn("502", logged)
        self.assertIn("Bad Gateway", logged)


if __name__ == "__main__":
    unittest.main()
