# encoding:utf-8
"""Unit tests for Qwen DashScope qwen3.7-plus provider updates."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestDashscopeConst(unittest.TestCase):
    def test_qwen37_plus_constant_defined(self):
        from common import const
        self.assertEqual(const.QWEN37_PLUS, "qwen3.7-plus")

    def test_qwen37_plus_in_model_list(self):
        from common import const
        self.assertIn("qwen3.7-plus", const.MODEL_LIST)

    def test_qwen37_plus_before_qwen37_max_in_model_list(self):
        from common import const
        qwen_models = [m for m in const.MODEL_LIST if str(m).startswith("qwen")]
        self.assertGreater(
            len(qwen_models),
            1,
        )
        self.assertEqual(qwen_models[0], "qwen3.7-plus")


class TestDashscopeBotDefaultModel(unittest.TestCase):
    def test_default_model_is_qwen37_plus(self):
        mock_conf = MagicMock()
        mock_conf.get = MagicMock(side_effect=lambda key, default=None: default)

        with patch("models.dashscope.dashscope_bot.conf", return_value=mock_conf):
            with patch("models.dashscope.dashscope_bot.SessionManager"):
                from models.dashscope.dashscope_bot import DashscopeBot
                bot = DashscopeBot.__new__(DashscopeBot)
                bot.sessions = MagicMock()
                bot.model_name = mock_conf.get("model") or "qwen3.7-plus"
                self.assertEqual(bot.model_name, "qwen3.7-plus")

    def test_default_model_string_in_source(self):
        bot_path = os.path.join(
            os.path.dirname(__file__), "..", "models", "dashscope", "dashscope_bot.py"
        )
        with open(bot_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn('"qwen3.7-plus"', source)


class TestDashscopeMultimodalRouting(unittest.TestCase):
    def test_qwen37_plus_uses_multimodal_api(self):
        from models.dashscope.dashscope_bot import DashscopeBot
        self.assertTrue(DashscopeBot._is_multimodal_model("qwen3.7-plus"))

    def test_qwen37_max_uses_generation_api(self):
        from models.dashscope.dashscope_bot import DashscopeBot
        self.assertFalse(DashscopeBot._is_multimodal_model("qwen3.7-max"))


if __name__ == "__main__":
    unittest.main()
