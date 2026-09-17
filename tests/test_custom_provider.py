# encoding:utf-8
"""
Unit tests for multiple custom (OpenAI-compatible) provider support (issue #2838).

Covers models/custom_provider.py:
  - Backward compatibility: legacy custom_api_key / custom_api_base fallback
  - Multi-provider selection via bot_type "custom:<id>" routing
  - parse_custom_bot_type helper
  - Robustness against malformed config (missing id, non-dict, non-list)
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


class TestParseCustomBotType(unittest.TestCase):
    """parse_custom_bot_type() parsing logic."""

    def setUp(self):
        from models.custom_provider import parse_custom_bot_type
        self.parse = parse_custom_bot_type

    def test_legacy_custom(self):
        is_custom, pid = self.parse("custom")
        self.assertTrue(is_custom)
        self.assertEqual(pid, "")

    def test_custom_with_id(self):
        is_custom, pid = self.parse("custom:3f2a9c1b")
        self.assertTrue(is_custom)
        self.assertEqual(pid, "3f2a9c1b")

    def test_non_custom(self):
        is_custom, pid = self.parse("openai")
        self.assertFalse(is_custom)
        self.assertEqual(pid, "")

    def test_empty(self):
        is_custom, pid = self.parse("")
        self.assertFalse(is_custom)
        self.assertEqual(pid, "")

    def test_none(self):
        is_custom, pid = self.parse(None)
        self.assertFalse(is_custom)
        self.assertEqual(pid, "")


class TestResolveCustomCredentials(unittest.TestCase):
    """resolve_custom_credentials() resolution order and fallbacks."""

    def setUp(self):
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

    # --- Multi-provider selection via bot_type ---

    def test_provider_selected_by_id(self):
        set_conf({
            "bot_type": "custom:abc12345",
            "custom_providers": [
                {"id": "sf001", "name": "provider-a", "api_key": "key-a",
                 "api_base": "https://api.example.com/v1", "model": "model-a"},
                {"id": "abc12345", "name": "provider-b", "api_key": "key-b",
                 "api_base": "https://api.example.org/v1", "model": "model-b"},
            ],
        })
        self.assertEqual(
            self.resolve(),
            ("key-b", "https://api.example.org/v1", "model-b"),
        )

    def test_id_not_found_falls_back_to_legacy(self):
        set_conf({
            "bot_type": "custom:ghost",
            "custom_api_key": "legacy-key",
            "custom_api_base": "https://legacy.example.com/v1",
            "custom_providers": [
                {"id": "sf001", "name": "provider-a", "api_key": "key-a",
                 "api_base": "https://api.example.com/v1"},
            ],
        })
        self.assertEqual(
            self.resolve(),
            ("legacy-key", "https://legacy.example.com/v1", None),
        )

    def test_provider_without_model_returns_none_model(self):
        set_conf({
            "bot_type": "custom:local01",
            "custom_providers": [
                {"id": "local01", "name": "local", "api_key": "", "api_base": "http://localhost:11434/v1"},
            ],
        })
        self.assertEqual(
            self.resolve(),
            ("", "http://localhost:11434/v1", None),
        )

    # --- Robustness against malformed config ---

    def test_malformed_entries_filtered_and_fallback(self):
        set_conf({
            "bot_type": "custom:nope",
            "custom_api_key": "legacy-key",
            "custom_api_base": "https://legacy.example.com/v1",
            "custom_providers": [
                {"name": "no-id", "api_key": "no-id-key"},   # invalid: no id
                "not-a-dict",                                  # invalid: wrong type
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
                {"id": "ok1", "name": "ok", "api_key": "k", "api_base": "https://x/v1"},
                {"name": "no-id", "api_key": "no-id"},   # dropped: no id
                123,                                       # dropped
            ],
        })
        providers = self.get_providers()
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["id"], "ok1")

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

    # --- Explicit bot_type (routes the call off the global provider) ---

    def test_explicit_bot_type_overrides_the_global_one(self):
        """A caller routing to another provider gets that provider's creds.

        This is the chat-fallback case: the global bot_type points at the
        primary provider, but the engaged fallback link names a different
        ``custom:<id>``. Reading the global value here paired the fallback's
        model id with the primary vendor's api_base, and upstream answered
        404 "model is not found".
        """
        set_conf({
            "bot_type": "custom:primary1",
            "custom_providers": [
                {"id": "primary1", "name": "primary", "api_key": "key-primary",
                 "api_base": "https://primary.example.com/v1", "model": "primary-model"},
                {"id": "backup22", "name": "backup", "api_key": "key-backup",
                 "api_base": "https://backup.example.com/v1", "model": "backup-model"},
            ],
        })
        # No argument -> global provider (unchanged legacy behavior)
        self.assertEqual(
            self.resolve(),
            ("key-primary", "https://primary.example.com/v1", "primary-model"),
        )
        # Explicit argument -> that provider, not the global one
        self.assertEqual(
            self.resolve("custom:backup22"),
            ("key-backup", "https://backup.example.com/v1", "backup-model"),
        )

    def test_explicit_non_custom_bot_type_uses_openai_fields(self):
        """An explicit non-custom type must not resolve custom credentials."""
        set_conf({
            "bot_type": "custom:primary1",
            "open_ai_api_key": "sk-openai",
            "open_ai_api_base": "https://api.openai.com/v1",
            "custom_providers": [
                {"id": "primary1", "name": "primary", "api_key": "key-primary",
                 "api_base": "https://primary.example.com/v1"},
            ],
        })
        self.assertEqual(
            self.resolve("chatGPT"),
            ("sk-openai", "https://api.openai.com/v1", None),
        )

    def test_explicit_legacy_custom_reads_flat_fields(self):
        """Passing the bare legacy 'custom' resolves the flat credentials."""
        set_conf({
            "bot_type": "custom:primary1",
            "custom_api_key": "legacy-key",
            "custom_api_base": "https://legacy.example.com/v1",
            "custom_providers": [
                {"id": "primary1", "name": "primary", "api_key": "key-primary",
                 "api_base": "https://primary.example.com/v1"},
            ],
        })
        self.assertEqual(
            self.resolve("custom"),
            ("legacy-key", "https://legacy.example.com/v1", None),
        )


class TestGenerateProviderId(unittest.TestCase):
    """generate_provider_id() produces valid short ids."""

    def test_length_and_hex(self):
        from models.custom_provider import generate_provider_id
        pid = generate_provider_id()
        self.assertEqual(len(pid), 8)
        # Must be valid hex characters
        int(pid, 16)

    def test_uniqueness(self):
        from models.custom_provider import generate_provider_id
        ids = {generate_provider_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)


class TestConfigDefaults(unittest.TestCase):
    """The new config fields must exist with safe defaults."""

    def test_default_config_has_custom_providers(self):
        from config import available_setting
        self.assertIn("custom_providers", available_setting)
        self.assertEqual(available_setting["custom_providers"], [])

    def test_default_config_no_custom_active_provider(self):
        """custom_active_provider was removed — replaced by bot_type routing."""
        from config import available_setting
        self.assertNotIn("custom_active_provider", available_setting)


class TestDragSensitiveNested(unittest.TestCase):
    """drag_sensitive() must mask api_key in nested structures."""

    def test_nested_api_key_masked(self):
        from config import drag_sensitive
        test_config = {
            "open_ai_api_key": "sk-1234567890abcdef",
            "custom_providers": [
                {"id": "x1", "name": "test", "api_key": "sk-nested-secret-key-long", "api_base": "https://x/v1"}
            ],
        }
        result = drag_sensitive(test_config)
        # Top-level key should be masked
        self.assertNotIn("1234567890abcdef", str(result))
        # Nested key should also be masked
        self.assertNotIn("nested-secret-key-long", str(result))
        # But the id/name/api_base should not be masked
        self.assertIn("x1", str(result))
        self.assertIn("test", str(result))
        self.assertIn("https://x/v1", str(result))

    def test_string_config_masked(self):
        from config import drag_sensitive
        import json
        test_str = json.dumps({
            "open_ai_api_key": "sk-1234567890abcdef",
            "custom_providers": [
                {"id": "x1", "api_key": "sk-nested-very-long-secret"}
            ],
        })
        result = drag_sensitive(test_str)
        self.assertNotIn("1234567890abcdef", result)
        self.assertNotIn("nested-very-long-secret", result)


if __name__ == "__main__":
    unittest.main()
