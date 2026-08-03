# encoding:utf-8
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub


class TestModelsHandler(unittest.TestCase):
    def test_config_handler_exposes_reasoning_effort_metadata(self):
        from channel.web.web_channel import ConfigHandler
        from config import Config

        local_config = Config({
            "agent": True,
            "model": "deepseek-v4-flash",
            "bot_type": "deepseek",
            "enable_thinking": True,
            "reasoning_effort": "max",
        })

        with patch("channel.web.web_channel._require_auth", lambda: None):
            with patch("channel.web.web_channel.conf", return_value=local_config):
                result = json.loads(ConfigHandler().GET())

        self.assertEqual(result["reasoning_effort"], "max")
        self.assertEqual(
            [item["value"] for item in result["providers"]["deepseek"]["reasoning"]["options"]],
            ["low", "high", "xhigh", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["deepseek"]["reasoning_by_model"]["deepseek-v4-flash"]["options"]],
            ["low", "high", "xhigh", "max"],
        )
        self.assertFalse(result["providers"]["deepseek"]["reasoning_by_model"]["deepseek-chat"]["supported"])
        self.assertEqual(
            [item["value"] for item in result["providers"]["zhipu"]["reasoning"]["options"]],
            ["low", "medium", "high", "xhigh", "max"],
        )
        self.assertFalse(result["providers"]["openai"]["reasoning"]["supported"])
        self.assertFalse(result["providers"]["gemini"]["reasoning"]["supported"])

    def test_reasoning_effort_is_editable_config_key(self):
        from channel.web.web_channel import ConfigHandler

        self.assertIn("reasoning_effort", ConfigHandler.EDITABLE_KEYS)

    def test_config_handler_hides_deepseek_effort_for_non_v4_models(self):
        from channel.web.web_channel import ConfigHandler
        from config import Config

        local_config = Config({
            "agent": True,
            "model": "deepseek-chat",
            "bot_type": "deepseek",
            "enable_thinking": True,
            "reasoning_effort": "max",
        })

        with patch("channel.web.web_channel._require_auth", lambda: None):
            with patch("channel.web.web_channel.conf", return_value=local_config):
                result = json.loads(ConfigHandler().GET())

        self.assertFalse(result["providers"]["deepseek"]["reasoning"]["supported"])

    def test_set_asr_capability_persists_provider_and_model(self):
        from channel.web.web_channel import ModelsHandler

        local_config = {}
        file_config = {}
        handler = ModelsHandler()

        with patch("channel.web.web_channel.conf", return_value=local_config):
            with patch.object(ModelsHandler, "_read_file_config", return_value=file_config):
                with patch.object(ModelsHandler, "_write_file_config") as write_file:
                    with patch.object(ModelsHandler, "_refresh_voice_routing") as refresh_voice:
                        result = json.loads(handler._handle_set_capability({
                            "capability": "asr",
                            "provider_id": "dashscope",
                            "model": "qwen3-asr-flash",
                        }))

        self.assertEqual(result["status"], "success")
        self.assertEqual(local_config["voice_to_text"], "dashscope")
        self.assertEqual(local_config["voice_to_text_model"], "qwen3-asr-flash")
        self.assertEqual(file_config["voice_to_text"], "dashscope")
        self.assertEqual(file_config["voice_to_text_model"], "qwen3-asr-flash")
        write_file.assert_called_once_with(file_config)
        refresh_voice.assert_called_once()

    def test_set_asr_empty_model_keeps_existing(self):
        # Switching provider with an empty model must not wipe a user's
        # hand-configured voice_to_text_model.
        from channel.web.web_channel import ModelsHandler

        local_config = {"voice_to_text_model": "qwen3-asr-flash"}
        file_config = {"voice_to_text_model": "qwen3-asr-flash"}
        handler = ModelsHandler()

        with patch("channel.web.web_channel.conf", return_value=local_config):
            with patch.object(ModelsHandler, "_read_file_config", return_value=file_config):
                with patch.object(ModelsHandler, "_write_file_config"):
                    with patch.object(ModelsHandler, "_refresh_voice_routing"):
                        result = json.loads(handler._handle_set_capability({
                            "capability": "asr",
                            "provider_id": "zhipu",
                            "model": "",
                        }))

        self.assertEqual(result["status"], "success")
        self.assertEqual(local_config["voice_to_text"], "zhipu")
        # Existing model preserved, not overwritten with "".
        self.assertEqual(local_config["voice_to_text_model"], "qwen3-asr-flash")
        self.assertEqual(file_config["voice_to_text_model"], "qwen3-asr-flash")
        self.assertEqual(result["model"], "qwen3-asr-flash")

    def test_asr_capability_exposes_provider_models(self):
        from channel.web.web_channel import ModelsHandler

        cap = ModelsHandler._asr_capability({
            "voice_to_text": "dashscope",
            "voice_to_text_model": "qwen3-asr-flash",
        })

        self.assertTrue(cap["editable"])
        self.assertEqual(cap["current_provider"], "dashscope")
        self.assertEqual(cap["current_model"], "qwen3-asr-flash")
        self.assertIn("provider_models", cap)
        self.assertIn("dashscope", cap["provider_models"])


if __name__ == "__main__":
    unittest.main()
