# encoding:utf-8
"""A vendor's API base is never left empty: clearing or resetting it restores
the vendor's endpoint, and an empty one in config.json is filled on load."""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.web.api.models import ModelsHandler


def _run(action, data, local_cfg):
    file_cfg = {}
    with patch("channel.web.api.models.conf", return_value=local_cfg), \
            patch.object(ModelsHandler, "_read_file_config", return_value=file_cfg), \
            patch.object(ModelsHandler, "_write_file_config"), \
            patch.object(ModelsHandler, "_reset_bridge"):
        out = json.loads(getattr(ModelsHandler(), action)(data))
    return out, file_cfg


def test_clearing_a_provider_restores_its_base():
    local_cfg = {"deepseek_api_key": "sk", "deepseek_api_base": "https://proxy.example.com/v1"}
    out, file_cfg = _run("_handle_delete_provider", {"provider_id": "deepseek"}, local_cfg)
    assert out["status"] == "success"
    assert file_cfg == {"deepseek_api_key": "", "deepseek_api_base": "https://api.deepseek.com/v1"}
    assert local_cfg["deepseek_api_base"] == "https://api.deepseek.com/v1"


def test_saving_an_empty_base_means_the_default():
    local_cfg = {"deepseek_api_base": "https://proxy.example.com/v1"}
    _, file_cfg = _run("_handle_set_provider", {"provider_id": "deepseek", "api_base": ""}, local_cfg)
    assert file_cfg["deepseek_api_base"] == "https://api.deepseek.com/v1"


def test_cowagent_base_stays_empty_to_follow_the_language():
    local_cfg = {"cowagent_api_key": "k", "cowagent_api_base": "https://example.com/v1"}
    _, file_cfg = _run("_handle_delete_provider", {"provider_id": "cowagent"}, local_cfg)
    assert file_cfg["cowagent_api_base"] == ""


def test_empty_base_in_config_file_is_filled_on_load(tmp_path, monkeypatch):
    import config as config_module

    (tmp_path / "config.json").write_text(
        json.dumps({"deepseek_api_base": "", "cowagent_api_base": ""}), encoding="utf-8",
    )
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_BASE", raising=False)
    # load_config rebinds the module-level singleton; restore the original after.
    monkeypatch.setattr(config_module, "config", config_module.config)
    config_module.load_config()
    assert config_module.conf().get("deepseek_api_base") == "https://api.deepseek.com/v1"
    assert config_module.conf().get("cowagent_api_base") == ""
