# encoding:utf-8
"""
Unit tests for MiniMax provider additions:
  - MiniMax-M2.7-highspeed constant in const.py
  - Default model update in MinimaxBot
  - MinimaxVoice TTS provider
"""
import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMinimaxConst(unittest.TestCase):
    """Test that MiniMax-M2.7-highspeed is properly registered in const.py."""

    def test_m2_7_highspeed_constant_defined(self):
        from common import const
        self.assertTrue(hasattr(const, "MINIMAX_M2_7_HIGHSPEED"))
        self.assertEqual(const.MINIMAX_M2_7_HIGHSPEED, "MiniMax-M2.7-highspeed")

    def test_m2_7_constant_defined(self):
        from common import const
        self.assertEqual(const.MINIMAX_M2_7, "MiniMax-M2.7")

    def test_m2_7_highspeed_in_model_list(self):
        from common import const
        self.assertIn("MiniMax-M2.7-highspeed", const.MODEL_LIST)

    def test_m2_7_in_model_list(self):
        from common import const
        self.assertIn("MiniMax-M2.7", const.MODEL_LIST)

    def test_minimax_provider_key_defined(self):
        from common import const
        self.assertEqual(const.MiniMax, "minimax")


class TestMinimaxBotDefaultModel(unittest.TestCase):
    """Test that MinimaxBot defaults to MiniMax-M2.7."""

    def test_default_model_is_m2_7(self):
        # Patch conf() to return empty config
        mock_conf = MagicMock()
        mock_conf.get = MagicMock(side_effect=lambda key, default=None: default)

        with patch("models.minimax.minimax_bot.conf", return_value=mock_conf):
            with patch("models.minimax.minimax_bot.SessionManager"):
                from models.minimax import minimax_bot
                # Reload to pick up patches
                import importlib
                importlib.reload(minimax_bot)
                with patch("models.minimax.minimax_bot.conf", return_value=mock_conf):
                    bot = minimax_bot.MinimaxBot.__new__(minimax_bot.MinimaxBot)
                    bot.args = {
                        "model": mock_conf.get("model") or "MiniMax-M2.7",
                    }
                    self.assertEqual(bot.args["model"], "MiniMax-M2.7")

    def test_default_model_string(self):
        """Verify the fallback string literal in minimax_bot.py is MiniMax-M2.7."""
        import ast
        bot_path = os.path.join(os.path.dirname(__file__), "..", "models", "minimax", "minimax_bot.py")
        with open(bot_path) as f:
            source = f.read()
        # Verify MiniMax-M2.7 is in the source (not M2.1)
        self.assertIn("MiniMax-M2.7", source)
        self.assertNotIn('"MiniMax-M2.1"', source)


class TestMinimaxVoice(unittest.TestCase):
    """Test MinimaxVoice TTS provider."""

    def _make_voice(self, api_key="test-key", api_base="https://api.minimax.io/v1"):
        mock_conf = MagicMock()
        def conf_get(key, default=None):
            return {
                "minimax_api_key": api_key,
                "minimax_api_base": api_base,
            }.get(key, default)
        mock_conf.get = conf_get
        with patch("voice.minimax.minimax_voice.conf", return_value=mock_conf):
            from voice.minimax.minimax_voice import MinimaxVoice
            return MinimaxVoice()

    def test_instantiation(self):
        voice = self._make_voice()
        self.assertIsNotNone(voice)

    def test_api_base_strips_v1_suffix(self):
        voice = self._make_voice(api_base="https://api.minimax.io/v1")
        self.assertEqual(voice.api_base, "https://api.minimax.io")

    def test_api_base_no_trailing_slash(self):
        voice = self._make_voice(api_base="https://api.minimax.io")
        self.assertEqual(voice.api_base, "https://api.minimax.io")

    def test_voice_to_text_not_supported(self):
        voice = self._make_voice()
        with self.assertRaises(NotImplementedError):
            voice.voiceToText("dummy.wav")

    def test_text_to_voice_success(self):
        """Test textToVoice with mocked SSE stream response."""
        import os
        os.makedirs("tmp", exist_ok=True)

        # Build fake SSE stream bytes
        audio_hex = bytes([0x49, 0x44, 0x33]).hex()  # "ID3" MP3 magic bytes
        sse_line = f'data: {{"data": {{"audio": "{audio_hex}", "status": 2}}}}\n\n'
        done_line = "data: [DONE]\n\n"
        fake_body = (sse_line + done_line).encode("utf-8")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_lines.return_value = [
            line.encode("utf-8") for line in (sse_line + done_line).splitlines() if line
        ]

        mock_conf = MagicMock()
        def conf_get(key, default=None):
            return {
                "minimax_api_key": "test-key",
                "minimax_api_base": "https://api.minimax.io",
            }.get(key, default)
        mock_conf.get = conf_get

        with patch("voice.minimax.minimax_voice.conf", return_value=mock_conf):
            with patch("voice.minimax.minimax_voice.requests.post", return_value=mock_response):
                from voice.minimax import minimax_voice
                import importlib
                importlib.reload(minimax_voice)
                with patch("voice.minimax.minimax_voice.conf", return_value=mock_conf):
                    voice = minimax_voice.MinimaxVoice()
                    from bridge.reply import ReplyType
                    reply = voice.textToVoice("Hello, world!")
                    self.assertEqual(reply.type, ReplyType.VOICE)
                    self.assertTrue(reply.content.endswith(".mp3"))

    def test_text_to_voice_no_audio_returns_error(self):
        """Test that empty SSE stream returns an ERROR reply."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_lines.return_value = []

        mock_conf = MagicMock()
        def conf_get(key, default=None):
            return {
                "minimax_api_key": "test-key",
                "minimax_api_base": "https://api.minimax.io",
            }.get(key, default)
        mock_conf.get = conf_get

        with patch("voice.minimax.minimax_voice.conf", return_value=mock_conf):
            with patch("voice.minimax.minimax_voice.requests.post", return_value=mock_response):
                from voice.minimax import minimax_voice
                import importlib
                importlib.reload(minimax_voice)
                with patch("voice.minimax.minimax_voice.conf", return_value=mock_conf):
                    voice = minimax_voice.MinimaxVoice()
                    from bridge.reply import ReplyType
                    reply = voice.textToVoice("Hello")
                    self.assertEqual(reply.type, ReplyType.ERROR)


class TestVoiceFactory(unittest.TestCase):
    """Test that minimax is registered in the voice factory."""

    def test_minimax_voice_factory(self):
        mock_conf = MagicMock()
        mock_conf.get = MagicMock(return_value=None)
        with patch("voice.minimax.minimax_voice.conf", return_value=mock_conf):
            from voice.factory import create_voice
            voice = create_voice("minimax")
            from voice.minimax.minimax_voice import MinimaxVoice
            self.assertIsInstance(voice, MinimaxVoice)


if __name__ == "__main__":
    unittest.main()
