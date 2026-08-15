# encoding:utf-8
import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestCustomVoice(unittest.TestCase):
    CUSTOM_PROVIDERS = {
        "custom_providers": [
            {"id": "abc12345", "name": "MyVendor", "api_key": "sk-test",
             "api_base": "https://my.vendor/v1"},
        ],
    }

    def conf_stack(self, conf):
        """Patch both conf references the module chain reads: the voice
        module's own import (legacy flat keys) and models.custom_provider's
        (custom_providers lookup)."""
        stack = ExitStack()
        stack.enter_context(patch("voice.custom.custom_voice.conf", return_value=conf))
        stack.enter_context(patch("models.custom_provider.conf", return_value=conf))
        return stack

    def test_factory_creates_custom_voice(self):
        from voice.custom.custom_voice import CustomVoice
        from voice.factory import create_voice

        self.assertIsInstance(create_voice("custom:abc12345"), CustomVoice)
        self.assertIsInstance(create_voice("custom"), CustomVoice)

    def test_resolve_credentials_multi_provider_and_legacy(self):
        from voice.custom.custom_voice import CustomVoice

        voice = CustomVoice("custom:abc12345")
        with self.conf_stack(self.CUSTOM_PROVIDERS):
            api_key, api_base = voice._resolve_credentials()
        self.assertEqual(api_key, "sk-test")
        self.assertEqual(api_base, "https://my.vendor/v1")

        legacy = CustomVoice("custom")
        flat = {"custom_api_key": "sk-flat", "custom_api_base": "https://flat/v1"}
        with self.conf_stack(flat):
            api_key, api_base = legacy._resolve_credentials()
        self.assertEqual(api_key, "sk-flat")
        self.assertEqual(api_base, "https://flat/v1")

    def test_voice_to_text_builds_transcription_request(self):
        from bridge.reply import ReplyType
        from voice.custom.custom_voice import CustomVoice

        conf = dict(self.CUSTOM_PROVIDERS)
        conf["voice_to_text_model"] = "fun-asr-large"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"text": "hello"}

        voice = CustomVoice("custom:abc12345")
        with self.conf_stack(conf):
            with patch("voice.custom.custom_voice.requests.post", return_value=response) as post:
                with patch("builtins.open", mock_open(read_data=b"audio-bytes")):
                    reply = voice.voiceToText("/fake/recording.webm")

        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(reply.content, "hello")
        self.assertEqual(post.call_args[0][0], "https://my.vendor/v1/audio/transcriptions")
        self.assertEqual(post.call_args.kwargs["data"]["model"], "fun-asr-large")
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-test"
        )

    def test_voice_to_text_requires_model(self):
        from bridge.reply import ReplyType
        from voice.custom.custom_voice import CustomVoice

        # No voice_to_text_model: custom vendors have no default, so the
        # request must not even be sent.
        voice = CustomVoice("custom:abc12345")
        with self.conf_stack(dict(self.CUSTOM_PROVIDERS)):
            with patch("voice.custom.custom_voice.requests.post") as post:
                reply = voice.voiceToText("/fake/recording.webm")

        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()

    def test_voice_to_text_unknown_provider_returns_error(self):
        from bridge.reply import ReplyType
        from voice.custom.custom_voice import CustomVoice

        voice = CustomVoice("custom:missing0")
        with self.conf_stack(self.CUSTOM_PROVIDERS):
            with patch("voice.custom.custom_voice.requests.post") as post:
                reply = voice.voiceToText("/fake/recording.webm")

        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()

    def test_text_to_voice_writes_audio_file(self):
        from bridge.reply import ReplyType
        from voice.custom.custom_voice import CustomVoice

        conf = dict(self.CUSTOM_PROVIDERS)
        conf["text_to_voice_model"] = "fun-tts-large"
        conf["tts_voice_id"] = "anna"
        response = MagicMock()
        response.status_code = 200
        response.content = b"mp3-bytes"

        voice = CustomVoice("custom:abc12345")
        with self.conf_stack(conf):
            with patch("voice.custom.custom_voice.requests.post", return_value=response) as post:
                with patch("builtins.open", mock_open()) as mocked_open:
                    reply = voice.textToVoice("你好")

        self.assertEqual(reply.type, ReplyType.VOICE)
        self.assertTrue(reply.content.startswith("tmp/"))
        self.assertTrue(reply.content.endswith(".mp3"))
        mocked_open().write.assert_called_once_with(b"mp3-bytes")
        self.assertEqual(post.call_args[0][0], "https://my.vendor/v1/audio/speech")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"model": "fun-tts-large", "input": "你好", "voice": "anna"},
        )

    def test_text_to_voice_requires_model(self):
        from bridge.reply import ReplyType
        from voice.custom.custom_voice import CustomVoice

        voice = CustomVoice("custom:abc12345")
        with self.conf_stack(dict(self.CUSTOM_PROVIDERS)):
            with patch("voice.custom.custom_voice.requests.post") as post:
                reply = voice.textToVoice("你好")

        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
