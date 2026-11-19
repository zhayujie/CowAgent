"""A custom provider's model may carry an optional display name (alias).

The alias is display only: the stored name stays the one sent to the API, a
catalog without aliases reads exactly as before, and built-in vendors never
store one.
"""
import json

import pytest

from models import model_catalog
from tests.test_session_model_catalog import _catalog_with

CUSTOM = "custom:abc12345"
CONFIG = {
    "bot_type": CUSTOM,
    "model": "deepseek/deepseek-flash",
    "custom_providers": [
        {"id": "abc12345", "name": "Gateway", "api_key": "sk-cust",
         "api_base": "https://gateway.example/v1"},
    ],
}


@pytest.fixture
def store(monkeypatch, tmp_path):
    path = tmp_path / "models.json"
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(path))
    model_catalog._invalidate()
    yield path
    model_catalog._invalidate()


def test_custom_provider_keeps_the_alias(store):
    model_catalog.save_catalog(CUSTOM, [
        {"name": "deepseek/deepseek-flash", "alias": "  DeepSeek-Flash  "},
        {"name": "kimi/kimi-k3"},
    ])

    entries = model_catalog.get_catalog(CUSTOM)
    assert entries[0] == {"name": "deepseek/deepseek-flash", "capabilities": ["text"],
                          "alias": "DeepSeek-Flash"}
    assert "alias" not in entries[1]
    assert json.loads(store.read_text())["providers"][CUSTOM]["overrides"][0]["alias"] == "DeepSeek-Flash"


def test_empty_or_redundant_alias_is_not_stored(store):
    model_catalog.save_catalog(CUSTOM, [
        {"name": "a", "alias": "   "},
        {"name": "b", "alias": "b"},
        {"name": "c", "alias": None},
    ])

    assert all("alias" not in e for e in model_catalog.get_catalog(CUSTOM))


def test_alias_is_capped(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "m", "alias": "x" * 200}])

    assert len(model_catalog.get_catalog(CUSTOM)[0]["alias"]) == model_catalog.MAX_ALIAS_LENGTH


def test_builtin_vendor_does_not_store_an_alias(store):
    model_catalog.save_catalog("deepseek", [{"name": "deepseek-flash", "alias": "Flash"}])

    assert model_catalog.get_catalog("deepseek") == [
        {"name": "deepseek-flash", "capabilities": ["text"]}]


def test_session_picker_gets_the_display_names(store):
    model_catalog.save_catalog(CUSTOM, [
        {"name": "deepseek/deepseek-flash", "alias": "DeepSeek-Flash"},
        {"name": "kimi/kimi-k3"},
        {"name": "embed/bge-m3", "alias": "BGE", "capabilities": ["embedding"]},
    ])

    group = next(c for c in _catalog_with(CONFIG) if c["id"] == CUSTOM)

    # The real names stay what the picker selects and sends.
    assert group["models"] == ["deepseek/deepseek-flash", "kimi/kimi-k3"]
    # Only models offered in the picker carry a label.
    assert group["labels"] == {"deepseek/deepseek-flash": "DeepSeek-Flash"}


def test_session_picker_without_aliases_is_unchanged(store):
    model_catalog.save_catalog(CUSTOM, [{"name": "deepseek/deepseek-flash"}])

    group = next(c for c in _catalog_with(CONFIG) if c["id"] == CUSTOM)

    assert "labels" not in group
