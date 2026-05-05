# encoding:utf-8
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestQianfanConstantsAndRouting(unittest.TestCase):
    def test_qianfan_provider_constant_defined(self):
        from common import const

        self.assertEqual(const.QIANFAN, "qianfan")

    def test_ernie_constants_are_in_model_list(self):
        from common import const

        self.assertEqual(const.ERNIE_45_TURBO_128K, "ernie-4.5-turbo-128k")
        self.assertEqual(const.ERNIE_45_TURBO_32K, "ernie-4.5-turbo-32k")
        self.assertEqual(const.ERNIE_X1_TURBO_32K, "ernie-x1-turbo-32k")
        self.assertIn(const.QIANFAN, const.MODEL_LIST)
        self.assertIn(const.ERNIE_45_TURBO_128K, const.MODEL_LIST)
        self.assertIn(const.ERNIE_45_TURBO_32K, const.MODEL_LIST)
        self.assertIn(const.ERNIE_X1_TURBO_32K, const.MODEL_LIST)

    def test_qianfan_config_keys_are_available(self):
        import config

        self.assertIn("qianfan_api_key", config.available_setting)
        self.assertIn("qianfan_api_base", config.available_setting)

    def test_agent_bridge_routes_ernie_models_to_qianfan(self):
        from bridge.agent_bridge import AgentLLMModel
        from common import const

        model = AgentLLMModel.__new__(AgentLLMModel)
        fake_conf = MagicMock()
        fake_conf.get.side_effect = lambda key, default=None: {
            "use_linkai": False,
            "linkai_api_key": "",
            "bot_type": "",
        }.get(key, default)

        with patch("bridge.agent_bridge.conf", return_value=fake_conf):
            self.assertEqual(
                AgentLLMModel._resolve_bot_type(model, "ernie-4.5-turbo-128k"),
                const.QIANFAN,
            )
            self.assertEqual(
                AgentLLMModel._resolve_bot_type(model, "qianfan"),
                const.QIANFAN,
            )

    def test_cow_cli_routes_ernie_models_to_qianfan(self):
        from common import const
        import plugins

        old_plugin_path = plugins.instance.current_plugin_path
        cow_cli_was_registered = "COW_CLI" in plugins.instance.plugins
        old_cow_cli_plugin = plugins.instance.plugins.get("COW_CLI")
        parent_had_cow_cli = hasattr(plugins, "cow_cli")
        old_parent_cow_cli = getattr(plugins, "cow_cli", None)
        module_names = ("plugins.cow_cli", "plugins.cow_cli.cow_cli")
        old_modules = {
            name: sys.modules[name]
            for name in module_names
            if name in sys.modules
        }
        plugins.instance.current_plugin_path = os.path.join(
            os.path.dirname(__file__), "..", "plugins", "cow_cli"
        )
        try:
            import plugins.cow_cli.cow_cli
            cow_cli_plugin = plugins.instance.plugins["COW_CLI"]
        finally:
            plugins.instance.current_plugin_path = old_plugin_path
            if cow_cli_was_registered:
                plugins.instance.plugins["COW_CLI"] = old_cow_cli_plugin
            else:
                plugins.instance.plugins.pop("COW_CLI", None)
            for name in module_names:
                if name in old_modules:
                    sys.modules[name] = old_modules[name]
                else:
                    sys.modules.pop(name, None)
            if parent_had_cow_cli:
                plugins.cow_cli = old_parent_cow_cli
            elif hasattr(plugins, "cow_cli"):
                delattr(plugins, "cow_cli")

        self.assertEqual(
            cow_cli_plugin._resolve_bot_type_for_model("ernie-4.5-turbo-128k"),
            const.QIANFAN,
        )
        self.assertEqual(
            cow_cli_plugin._resolve_bot_type_for_model("qianfan"),
            const.QIANFAN,
        )


class TestQianfanBot(unittest.TestCase):
    def _fake_conf(self, values=None):
        data = {
            "model": "ernie-4.5-turbo-128k",
            "qianfan_api_key": "test-qianfan-key",
            "qianfan_api_base": "https://qianfan.baidubce.com/v2",
            "temperature": 0.7,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "request_timeout": 180,
            "clear_memory_commands": ["#清除记忆"],
            "conversation_max_tokens": 1000,
            "expires_in_seconds": 3600,
        }
        if values:
            data.update(values)
        fake_conf = MagicMock()
        fake_conf.get.side_effect = lambda key, default=None: data.get(key, default)
        return fake_conf

    def test_bot_factory_returns_qianfan_bot(self):
        from common import const
        from models.bot_factory import create_bot

        fake_conf = self._fake_conf()
        with patch("models.qianfan.qianfan_bot.conf", return_value=fake_conf):
            with patch("models.qianfan.qianfan_bot.SessionManager"):
                bot = create_bot(const.QIANFAN)

        from models.qianfan.qianfan_bot import QianfanBot
        self.assertIsInstance(bot, QianfanBot)

    def test_default_model_uses_ernie_when_model_is_provider_alias(self):
        fake_conf = self._fake_conf({"model": "qianfan"})
        with patch("models.qianfan.qianfan_bot.conf", return_value=fake_conf):
            with patch("models.qianfan.qianfan_bot.SessionManager"):
                from models.qianfan.qianfan_bot import QianfanBot

                bot = QianfanBot()

        self.assertEqual(bot.args["model"], "ernie-4.5-turbo-128k")

    def test_reply_text_posts_openai_compatible_payload(self):
        fake_conf = self._fake_conf()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "你好，我是文心。"}}],
            "usage": {"total_tokens": 12, "completion_tokens": 6},
        }
        session = MagicMock()
        session.messages = [{"role": "user", "content": "你好"}]

        with patch("models.qianfan.qianfan_bot.conf", return_value=fake_conf):
            with patch("models.qianfan.qianfan_bot.SessionManager"):
                from models.qianfan.qianfan_bot import QianfanBot

                bot = QianfanBot()
                with patch("models.qianfan.qianfan_bot.requests.post", return_value=fake_response) as post:
                    result = bot.reply_text(session)

        self.assertEqual(result["content"], "你好，我是文心。")
        self.assertEqual(result["total_tokens"], 12)
        self.assertEqual(result["completion_tokens"], 6)
        post.assert_called_once()
        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        self.assertEqual(url, "https://qianfan.baidubce.com/v2/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-qianfan-key")
        self.assertEqual(kwargs["json"]["model"], "ernie-4.5-turbo-128k")
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "你好"}])

    def test_reply_text_returns_auth_error_for_401(self):
        fake_conf = self._fake_conf()
        fake_response = MagicMock()
        fake_response.status_code = 401
        fake_response.json.return_value = {"error": {"message": "invalid api key"}}
        fake_response.text = '{"error":{"message":"invalid api key"}}'
        session = MagicMock()
        session.messages = [{"role": "user", "content": "你好"}]

        with patch("models.qianfan.qianfan_bot.conf", return_value=fake_conf):
            with patch("models.qianfan.qianfan_bot.SessionManager"):
                from models.qianfan.qianfan_bot import QianfanBot

                bot = QianfanBot()
                with patch("models.qianfan.qianfan_bot.requests.post", return_value=fake_response):
                    result = bot.reply_text(session)

        self.assertEqual(result["completion_tokens"], 0)
        self.assertEqual(result["content"], "授权失败，请检查 Qianfan API Key 是否正确")

    def test_reply_text_returns_raw_message_for_non_json_error(self):
        fake_conf = self._fake_conf()
        fake_response = MagicMock()
        fake_response.status_code = 400
        fake_response.json.side_effect = ValueError
        fake_response.text = "bad gateway text"
        session = MagicMock()
        session.messages = [{"role": "user", "content": "你好"}]

        with patch("models.qianfan.qianfan_bot.conf", return_value=fake_conf):
            with patch("models.qianfan.qianfan_bot.SessionManager"):
                from models.qianfan.qianfan_bot import QianfanBot

                bot = QianfanBot()
                with patch("models.qianfan.qianfan_bot.requests.post", return_value=fake_response) as post:
                    result = bot.reply_text(session)

        self.assertEqual(result["completion_tokens"], 0)
        self.assertEqual(result["content"], "请求失败：bad gateway text")
        post.assert_called_once()


class TestQianfanSurfaces(unittest.TestCase):
    def _read(self, relative_path):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, relative_path), encoding="utf-8") as f:
            return f.read()

    def test_web_console_registers_qianfan_provider(self):
        source = self._read("channel/web/web_channel.py")

        self.assertIn('("qianfan", {', source)
        self.assertIn('"label": "百度千帆"', source)
        self.assertIn('"api_key_field": "qianfan_api_key"', source)
        self.assertIn('"api_base_key": "qianfan_api_base"', source)
        self.assertIn('"api_base_default": "https://qianfan.baidubce.com/v2"', source)

    def test_web_console_allows_qianfan_config_edits(self):
        source = self._read("channel/web/web_channel.py")

        self.assertIn('"qianfan_api_base"', source)
        self.assertIn('"qianfan_api_key"', source)

    def test_session_plugins_allow_qianfan(self):
        role_source = self._read("plugins/role/role.py")
        godcmd_source = self._read("plugins/godcmd/godcmd.py")

        self.assertIn("const.QIANFAN", role_source)
        self.assertIn("const.QIANFAN", godcmd_source)


class TestQianfanDocs(unittest.TestCase):
    def _read(self, relative_path):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, relative_path), encoding="utf-8") as f:
            return f.read()

    def test_qianfan_docs_exist_in_all_doc_locales(self):
        for path in (
            "docs/models/qianfan.mdx",
            "docs/en/models/qianfan.mdx",
            "docs/ja/models/qianfan.mdx",
        ):
            text = self._read(path)
            self.assertIn("qianfan_api_key", text)
            self.assertIn("https://qianfan.baidubce.com/v2", text)
            self.assertIn("ernie-4.5-turbo-128k", text)

    def test_model_indexes_link_qianfan(self):
        for path in (
            "docs/models/index.mdx",
            "docs/en/models/index.mdx",
            "docs/ja/models/index.mdx",
        ):
            text = self._read(path)
            self.assertIn('/models/qianfan', text)

    def test_readme_documents_native_qianfan_provider(self):
        text = self._read("README.md")

        self.assertIn('"model": "ernie-4.5-turbo-128k"', text)
        self.assertIn('"qianfan_api_key": ""', text)
        self.assertIn('"qianfan_api_base": "https://qianfan.baidubce.com/v2"', text)


if __name__ == "__main__":
    unittest.main()
