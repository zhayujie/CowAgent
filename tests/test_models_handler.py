# encoding:utf-8
import json
import os
import sys
import types
import unittest
from unittest.mock import mock_open, patch

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
        self.assertEqual(
            [item["value"] for item in result["providers"]["claudeAPI"]["reasoning_by_model"]["claude-opus-5"]["options"]],
            ["low", "medium", "high", "xhigh", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["claudeAPI"]["reasoning_by_model"]["claude-sonnet-4-6"]["options"]],
            ["low", "medium", "high", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["dashscope"]["reasoning_by_model"]["qwen3.8-max-preview"]["options"]],
            ["low", "medium", "xhigh"],
        )
        self.assertFalse(result["providers"]["dashscope"]["reasoning_by_model"]["qwen3.7-plus"]["supported"])
        self.assertEqual(
            [item["value"] for item in result["providers"]["moonshot"]["reasoning_by_model"]["kimi-k3"]["options"]],
            ["low", "high", "max"],
        )
        self.assertTrue(result["providers"]["moonshot"]["reasoning_by_model"]["kimi-k3"]["thinking_only"])
        self.assertFalse(result["providers"]["moonshot"]["reasoning_by_model"]["kimi-k2.7-code"]["supported"])
        self.assertFalse(result["providers"]["openai"]["reasoning"]["supported"])
        self.assertFalse(result["providers"]["gemini"]["reasoning"]["supported"])

    def test_reasoning_effort_is_editable_config_key(self):
        from channel.web.web_channel import ConfigHandler

        self.assertIn("reasoning_effort", ConfigHandler.EDITABLE_KEYS)
        self.assertIn("reasoning_effort_by_model", ConfigHandler.EDITABLE_KEYS)

    def test_config_save_rejects_non_dict_reasoning_effort_by_model(self):
        from channel.web.web_channel import ConfigHandler
        from config import Config

        local_config = Config({"reasoning_effort_by_model": {"deepseek:deepseek-v4-flash": "high"}})
        file_config = {"reasoning_effort_by_model": {"deepseek:deepseek-v4-flash": "high"}}
        payload = {"updates": {"reasoning_effort_by_model": "not-a-dict"}}

        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.header"), \
             patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode()), \
             patch("channel.web.web_channel.conf", return_value=local_config), \
             patch("channel.web.web_channel._read_config_file_for_write", return_value=file_config), \
             patch("builtins.open", mock_open()) as m:
            result = json.loads(ConfigHandler().POST())

        self.assertEqual(result["status"], "error")
        # Nothing written: the payload was rejected before the file write.
        m.assert_not_called()
        # The in-memory config is untouched too.
        self.assertEqual(local_config.get("reasoning_effort_by_model"), {"deepseek:deepseek-v4-flash": "high"})

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

    def test_asr_capability_includes_custom_providers(self):
        from channel.web.web_channel import ModelsHandler

        custom_conf = {"custom_providers": [
            {"id": "abc12345", "name": "MyVendor", "api_key": "sk-test-1234567890",
             "api_base": "https://my.vendor/v1"},
        ]}
        with patch("models.custom_provider.conf", return_value=custom_conf):
            cap = ModelsHandler._asr_capability({
                "voice_to_text": "custom:abc12345",
                "voice_to_text_model": "fun-asr-large",
            })

        # The expanded custom:<id> entry is selectable, and a saved custom
        # provider/model round-trips as the current selection.
        self.assertIn("custom:abc12345", cap["providers"])
        for builtin in ("openai", "dashscope", "zhipu", "linkai"):
            self.assertIn(builtin, cap["providers"])
        self.assertEqual(cap["current_provider"], "custom:abc12345")
        self.assertEqual(cap["current_model"], "fun-asr-large")

    def test_tts_capability_includes_custom_providers(self):
        from channel.web.web_channel import ModelsHandler

        custom_conf = {"custom_providers": [
            {"id": "abc12345", "name": "MyVendor", "api_key": "sk-test-1234567890",
             "api_base": "https://my.vendor/v1"},
        ]}
        with patch("models.custom_provider.conf", return_value=custom_conf):
            cap = ModelsHandler._tts_capability({
                "text_to_voice": "custom:abc12345",
                "text_to_voice_model": "fun-tts-large",
                "tts_voice_id": "anna",
            })

        self.assertIn("custom:abc12345", cap["providers"])
        self.assertEqual(cap["current_provider"], "custom:abc12345")
        self.assertEqual(cap["current_model"], "fun-tts-large")
        self.assertEqual(cap["current_voice"], "anna")

    def test_tts_capability_without_custom_providers_keeps_builtin_list(self):
        from channel.web.web_channel import ModelsHandler

        with patch("models.custom_provider.conf", return_value={}):
            cap = ModelsHandler._tts_capability({
                "text_to_voice": "openai",
                "text_to_voice_model": "tts-1",
            })

        self.assertEqual(cap["current_provider"], "openai")
        self.assertEqual(cap["current_model"], "tts-1")
        self.assertTrue(all(not p.startswith("custom:") for p in cap["providers"]))


if __name__ == "__main__":
    unittest.main()
