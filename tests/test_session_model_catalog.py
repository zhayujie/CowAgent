# encoding:utf-8
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


def _catalog_with(config):
    from channel.web import web_channel

    with patch.object(web_channel, "conf", return_value=config), \
            patch("models.custom_provider.conf", return_value=config):
        return web_channel._session_model_catalog()


class TestSessionModelCatalog(unittest.TestCase):
    def test_custom_model_on_builtin_provider_is_selectable(self):
        """A custom model name pinned to a built-in provider shows up."""
        catalog = _catalog_with({
            "bot_type": "openai",
            "open_ai_api_key": "sk-xxx",
            "model": "gpt-5-custom-preview",
        })
        openai = next((c for c in catalog if c["id"] == "openai"), None)
        self.assertIsNotNone(openai)
        self.assertIn("gpt-5-custom-preview", openai["models"])
        # The custom model is listed first so it is easy to find + re-select.
        self.assertEqual(openai["models"][0], "gpt-5-custom-preview")

    def test_custom_provider_with_model_is_selectable(self):
        catalog = _catalog_with({
            "bot_type": "deepseek",
            "deepseek_api_key": "sk-ds",
            "model": "deepseek-chat",
            "custom_providers": [
                {"id": "abc12345", "name": "MyVendor", "api_key": "sk-cust",
                 "api_base": "https://my.vendor/v1", "model": "my-model-x"},
            ],
        })
        cust = next((c for c in catalog if c["id"] == "custom:abc12345"), None)
        self.assertIsNotNone(cust)
        self.assertEqual(cust["label"], {"zh": "MyVendor", "en": "MyVendor"})
        self.assertIn("my-model-x", cust["models"])

    def test_active_custom_provider_without_default_model_uses_global_model(self):
        """A custom provider added via the UI (no `model` field) but active still
        exposes the globally active model so it can be selected in chat."""
        catalog = _catalog_with({
            "bot_type": "custom:abc12345",
            "model": "vendor-model-7b",
            "custom_providers": [
                {"id": "abc12345", "name": "Local vLLM", "api_key": "sk-cust",
                 "api_base": "http://localhost:8000/v1"},
            ],
        })
        cust = next((c for c in catalog if c["id"] == "custom:abc12345"), None)
        self.assertIsNotNone(cust)
        self.assertIn("vendor-model-7b", cust["models"])

    def test_custom_provider_with_key_but_no_model_when_inactive_is_skipped(self):
        """No concrete model to offer -> not rendered as an empty group."""
        catalog = _catalog_with({
            "bot_type": "openai",
            "open_ai_api_key": "sk-xxx",
            "model": "gpt-4o",
            "custom_providers": [
                {"id": "def67890", "name": "Idle", "api_key": "sk-cust",
                 "api_base": "https://idle/v1"},
            ],
        })
        self.assertIsNone(next((c for c in catalog if c["id"] == "custom:def67890"), None))


if __name__ == "__main__":
    unittest.main()
