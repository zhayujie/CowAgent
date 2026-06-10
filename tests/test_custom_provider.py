# encoding:utf-8
"""
Unit tests for multiple custom (OpenAI-compatible) provider support (issue #2838).

Covers models/custom_provider.py:
  - Backward compatibility: legacy custom_api_key / custom_api_base fallback
  - Multi-provider selection via custom_providers / custom_active_provider
  - Robustness against malformed config (missing name, non-dict, non-list)
"""
import sys
import os
import unittest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module
from config import Config


def set_conf(d):
    """Install a fresh Config as the global config used by conf()."""
    config_module.config = Config(d)


class TestResolveCustomCredentials(unittest.TestCase):
    """resolve_custom_credentials() resolution order and fallbacks."""

    def setUp(self):
        # Import here so the module picks up our config-swapping helper.
        from models.custom_provider import resolve_custom_credentials, get_custom_providers
        self.resolve = resolve_custom_credentials
        self.get_providers = get_custom_providers

    # --- Backward compatibility ---

    def test_legacy_fallback_when_no_providers(self):
        set_conf({
            "bot_type": "custom",
            "custom_api_key": "legacy-key",
            "custom_api_base": "https://legacy.example.com/v1",
        })
        self.assertEqual(
            self.resolve(),
            ("legacy-key", "https://legacy.example.com/v1", None),
        )

    def test_empty_config(self):
        set_conf({"bot_type": "custom"})
        self.assertEqual(self.resolve(), ("", None, None))

    # --- Multi-provider selection ---

    def test_multi_providers_no_active_uses_first(self):
        set_conf({
            "bot_type": "custom",
            "custom_providers": [
                {"name": "siliconflow", "api_key": "sf-key",
                 "api_base": "https://api.siliconflow.cn/v1", "model": "deepseek-ai/DeepSeek-V3"},
                {"name": "qiniu", "api_key": "qn-key",
                 "api_base": "https://api.qnaigc.com/v1", "model": "deepseek-v3"},
            ],
        })
        self.assertEqual(
            self.resolve(),
            ("sf-key", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"),
        )

    def test_active_provider_selected(self):
        set_conf({
            "bot_type": "custom",
            "custom_active_provider": "qiniu",
            "custom_providers": [
                {"name": "siliconflow", "api_key": "sf-key",
                 "api_base": "https://api.siliconflow.cn/v1", "model": "m1"},
                {"name": "qiniu", "api_key": "qn-key",
                 "api_base": "https://api.qnaigc.com/v1", "model": "deepseek-v3"},
            ],
        })
        self.assertEqual(
            self.resolve(),
            ("qn-key", "https://api.qnaigc.com/v1", "deepseek-v3"),
        )

    def test_active_name_missing_falls_back_to_first(self):
        set_conf({
            "bot_type": "custom",
            "custom_active_provider": "ghost",
            "custom_providers": [
                {"name": "siliconflow", "api_key": "sf-key",
                 "api_base": "https://api.siliconflow.cn/v1"},
            ],
        })
        self.assertEqual(
            self.resolve(),
            ("sf-key", "https://api.siliconflow.cn/v1", None),
        )

    def test_provider_without_model_returns_none_model(self):
        set_conf({
            "bot_type": "custom",
            "custom_providers": [
                {"name": "local", "api_key": "", "api_base": "http://localhost:11434/v1"},
            ],
        })
        self.assertEqual(
            self.resolve(),
            ("", "http://localhost:11434/v1", None),
        )

    # --- Robustness against malformed config ---

    def test_malformed_entries_filtered_and_fallback(self):
        set_conf({
            "bot_type": "custom",
            "custom_api_key": "legacy-key",
            "custom_api_base": "https://legacy.example.com/v1",
            "custom_providers": [
                {"api_key": "no-name-key"},   # invalid: no name
                "not-a-dict",                 # invalid: wrong type
            ],
        })
        # All entries invalid -> treated as empty -> legacy fallback
        self.assertEqual(
            self.resolve(),
            ("legacy-key", "https://legacy.example.com/v1", None),
        )

    def test_get_custom_providers_filters_invalid(self):
        set_conf({
            "bot_type": "custom",
            "custom_providers": [
                {"name": "ok", "api_key": "k", "api_base": "https://x/v1"},
                {"api_key": "no-name"},   # dropped
                123,                       # dropped
            ],
        })
        providers = self.get_providers()
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["name"], "ok")

    def test_custom_providers_not_a_list_falls_back(self):
        set_conf({
            "bot_type": "custom",
            "custom_api_key": "legacy-key",
            "custom_api_base": "https://legacy.example.com/v1",
            "custom_providers": "oops-a-string",
        })
        self.assertEqual(
            self.resolve(),
            ("legacy-key", "https://legacy.example.com/v1", None),
        )


class TestConfigDefaults(unittest.TestCase):
    """The new config fields must exist with safe defaults."""

    def test_default_config_has_custom_providers(self):
        from config import available_setting
        self.assertIn("custom_providers", available_setting)
        self.assertEqual(available_setting["custom_providers"], [])

    def test_default_config_has_active_provider(self):
        from config import available_setting
        self.assertIn("custom_active_provider", available_setting)
        self.assertEqual(available_setting["custom_active_provider"], "")


if __name__ == "__main__":
    unittest.main()
