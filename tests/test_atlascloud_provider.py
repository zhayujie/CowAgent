# encoding:utf-8
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAtlasCloudRegistration(unittest.TestCase):
    def test_constant_and_config_keys(self):
        import config
        from common import const

        self.assertEqual(const.ATLASCLOUD, "atlascloud")
        self.assertIn("atlascloud_api_key", config.available_setting)
        self.assertIn("atlascloud_api_base", config.available_setting)
        self.assertEqual(config.CONFIG_TO_ENV["atlascloud_api_key"], "ATLASCLOUD_API_KEY")
        self.assertEqual(config.CONFIG_TO_ENV["atlascloud_api_base"], "ATLASCLOUD_API_BASE")

    def test_web_console_registers_provider(self):
        from channel.web.core import providers

        provider = providers.PROVIDER_MODELS["atlascloud"]
        self.assertEqual(provider["api_key_field"], "atlascloud_api_key")
        self.assertEqual(provider["api_base_key"], "atlascloud_api_base")
        self.assertEqual(provider["api_base_default"], "https://api.atlascloud.ai/v1")
        self.assertIn("deepseek-ai/deepseek-v4-flash", provider["models"])

    def test_web_console_allows_config_edits(self):
        from channel.web.api.config import ConfigHandler

        self.assertIn("atlascloud_api_key", ConfigHandler.EDITABLE_KEYS)
        self.assertIn("atlascloud_api_base", ConfigHandler.EDITABLE_KEYS)

    def test_bot_factory_builds_atlascloud_bot(self):
        from common import const
        from models.atlascloud.atlascloud_bot import AtlasCloudBot
        from models.bot_factory import create_bot

        self.assertIsInstance(create_bot(const.ATLASCLOUD), AtlasCloudBot)

    def test_vendor_prefixed_model_ids_follow_the_configured_bot_type(self):
        # "deepseek-ai/..." would otherwise match the "deepseek" prefix rule.
        from bridge.agent_bridge import AgentLLMModel

        model = AgentLLMModel.__new__(AgentLLMModel)
        fake_conf = MagicMock()
        fake_conf.get.side_effect = lambda key, default=None: {
            "bot_type": "atlascloud",
        }.get(key, default)
        with patch("bridge.agent_bridge.conf", return_value=fake_conf):
            self.assertEqual(
                model._resolve_bot_type("deepseek-ai/deepseek-v4-flash"), "atlascloud"
            )


class TestAtlasCloudBot(unittest.TestCase):
    def _conf(self, values):
        fake = MagicMock()
        fake.get.side_effect = lambda key, default=None: values.get(key, default)
        return fake

    def test_api_config_uses_own_key_and_base(self):
        from models.atlascloud import atlascloud_bot

        values = {
            "model": "moonshotai/kimi-k3",
            "atlascloud_api_key": "test-key",
            "atlascloud_api_base": "https://api.atlascloud.ai/v1/chat/completions/",
        }
        with patch.object(atlascloud_bot, "conf", return_value=self._conf(values)):
            bot = atlascloud_bot.AtlasCloudBot()
            cfg = bot.get_api_config()

        self.assertEqual(cfg["api_key"], "test-key")
        self.assertEqual(cfg["api_base"], "https://api.atlascloud.ai/v1")
        self.assertEqual(cfg["model"], "moonshotai/kimi-k3")

    def test_defaults_when_unconfigured(self):
        from models.atlascloud import atlascloud_bot

        with patch.object(atlascloud_bot, "conf", return_value=self._conf({})):
            bot = atlascloud_bot.AtlasCloudBot()
            cfg = bot.get_api_config()

        self.assertEqual(cfg["api_base"], atlascloud_bot.DEFAULT_API_BASE)
        self.assertEqual(cfg["model"], atlascloud_bot.DEFAULT_MODEL)

    def test_reply_text_posts_chat_completion(self):
        from models.atlascloud import atlascloud_bot

        values = {"model": "deepseek-ai/deepseek-v4-flash", "atlascloud_api_key": "k"}
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"total_tokens": 7, "completion_tokens": 2},
        }
        session = MagicMock(messages=[{"role": "user", "content": "yo"}])
        with patch.object(atlascloud_bot, "conf", return_value=self._conf(values)), \
                patch.object(atlascloud_bot.requests, "post", return_value=resp) as post:
            bot = atlascloud_bot.AtlasCloudBot()
            result = bot.reply_text(session)

        self.assertEqual(result["content"], "hi")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.atlascloud.ai/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer k")
        self.assertEqual(kwargs["json"]["model"], "deepseek-ai/deepseek-v4-flash")

    def test_unauthorized_reports_key_problem(self):
        from models.atlascloud import atlascloud_bot

        resp = MagicMock(status_code=401)
        resp.json.return_value = {"error": {"message": "bad key"}}
        with patch.object(atlascloud_bot, "conf", return_value=self._conf({})):
            bot = atlascloud_bot.AtlasCloudBot()
            result = bot._error_result(resp, None)

        self.assertEqual(result["completion_tokens"], 0)
        self.assertIn("Atlas Cloud", result["content"])


if __name__ == "__main__":
    unittest.main()
