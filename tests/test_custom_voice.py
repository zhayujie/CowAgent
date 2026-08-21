# encoding:utf-8
"""
Unit tests for voice/custom/custom_voice.py and its factory routing.

Covers:
  - voice.factory.create_voice("custom[:<id>]") → CustomVoice
  - credential resolution: custom_providers lookup by id + legacy flat config
  - voiceToText / textToVoice request construction (OpenAI-compatible
    /audio/transcriptions and /audio/speech) and error paths
"""
import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.custom.custom_voice import CustomVoice
from voice.factory import create_voice


class TestCustomVoice(unittest.TestCase):
    CUSTOM_PROVIDERS = {
        "custom_providers": [
            {"id": "abc12345", "name": "MyVendor", "api_key": "sk-test",
             "api_base": "https://my.vendor/v1"},
        ],
    }

    @staticmethod
    def conf(**overrides):
        """Custom-vendor config for this suite, with per-test overrides.

        Patched into both conf references the module chain reads: the voice
        module's own import (legacy flat keys) and models.custom_provider's
        (custom_providers lookup).
        """
        merged = {**TestCustomVoice.CUSTOM_PROVIDERS, **overrides}
        stack = ExitStack()
        stack.enter_context(patch("voice.custom.custom_voice.conf", return_value=merged))
        stack.enter_context(patch("models.custom_provider.conf", return_value=merged))
        return stack

    def test_factory_creates_custom_voice(self):
        self.assertIsInstance(create_voice("custom:abc12345"), CustomVoice)
        self.assertIsInstance(create_voice("custom"), CustomVoice)

    def test_resolve_credentials_multi_provider(self):
        voice = CustomVoice("custom:abc12345")
        with self.conf():
            api_key, api_base = voice._resolve_credentials()
        self.assertEqual(api_key, "sk-test")
        self.assertEqual(api_base, "https://my.vendor/v1")

    def test_resolve_credentials_legacy_flat_config(self):
        voice = CustomVoice("custom")
        with self.conf(custom_api_key="sk-flat", custom_api_base="https://flat/v1"):
            api_key, api_base = voice._resolve_credentials()
        self.assertEqual(api_key, "sk-flat")
        self.assertEqual(api_base, "https://flat/v1")

    def test_voice_to_text_builds_transcription_request(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"text": "hello"}

        voice = CustomVoice("custom:abc12345")
        with self.conf(voice_to_text_model="fun-asr-large"):
            with patch("voice.custom.custom_voice.requests.post", return_value=response) as post:
                with patch("builtins.open", mock_open(read_data=b"audio-bytes")):
                    reply = voice.voiceToText("/fake/recording.webm")

        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(reply.content, "hello")
        self.assertEqual(post.call_args[0][0], "https://my.vendor/v1/audio/transcriptions")
        self.assertEqual(post.call_args.kwargs["data"]["model"], "fun-asr-large")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-test")

    def test_voice_to_text_requires_model(self):
        # Custom vendors have no default model: the request must not be sent.
        voice = CustomVoice("custom:abc12345")
        with self.conf():
            with patch("voice.custom.custom_voice.requests.post") as post:
                reply = voice.voiceToText("/fake/recording.webm")

        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()

    def test_voice_to_text_unknown_provider_returns_error(self):
        voice = CustomVoice("custom:missing0")
        with self.conf():
            with patch("voice.custom.custom_voice.requests.post") as post:
                reply = voice.voiceToText("/fake/recording.webm")

        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()

    def test_text_to_voice_writes_audio_file(self):
        response = MagicMock()
        response.status_code = 200
        response.content = b"mp3-bytes"

        voice = CustomVoice("custom:abc12345")
        with self.conf(text_to_voice_model="fun-tts-large", tts_voice_id="anna"):
            with patch("voice.custom.custom_voice.requests.post", return_value=response) as post:
                with patch("builtins.open", mock_open()) as mocked_open:
                    reply = voice.textToVoice("你好")

        self.assertEqual(reply.type, ReplyType.VOICE)
        self.assertTrue(reply.content.startswith("tmp/") and reply.content.endswith(".mp3"))
        mocked_open().write.assert_called_once_with(b"mp3-bytes")
        self.assertEqual(post.call_args[0][0], "https://my.vendor/v1/audio/speech")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"model": "fun-tts-large", "input": "你好", "voice": "anna"},
        )

    def test_text_to_voice_requires_model(self):
        voice = CustomVoice("custom:abc12345")
        with self.conf():
            with patch("voice.custom.custom_voice.requests.post") as post:
                reply = voice.textToVoice("你好")

        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
