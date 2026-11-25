# encoding:utf-8
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common import const
from models.llmtr_provider import default_llmtr_api_base, resolve_llmtr_credentials


def test_default_base_is_the_public_endpoint():
    assert default_llmtr_api_base() == "https://llmtr.com/v1"
    assert const.LLMTR == "llmtr"
    assert const.LLMTR_API_BASE == "https://llmtr.com/v1"


def test_resolve_prefers_config_then_env(monkeypatch):
    monkeypatch.delenv("LLMTR_API_KEY", raising=False)
    monkeypatch.delenv("LLMTR_API_BASE", raising=False)
    with patch("models.llmtr_provider.conf", return_value={
        "llmtr_api_key": "llmtr-from-config",
        "llmtr_api_base": "https://example.test/v1/",
    }):
        key, base = resolve_llmtr_credentials()
    assert key == "llmtr-from-config"
    assert base == "https://example.test/v1"

    with patch("models.llmtr_provider.conf", return_value={}):
        monkeypatch.setenv("LLMTR_API_KEY", "llmtr-from-env")
        key, base = resolve_llmtr_credentials()
    assert key == "llmtr-from-env"
    assert base == "https://llmtr.com/v1"
