"""Settings persistence and execution-host validation, without a running server."""
import copy
import json

import pytest

from channel.web.api import bash_settings as api


@pytest.fixture
def settings(monkeypatch, tmp_path):
    cfg = {"tools": {"bash": {"timeout": 45}, "read": {"other": True}}, "model": "keep"}
    persisted = copy.deepcopy(cfg)
    monkeypatch.setattr(api, "conf", lambda: cfg)
    monkeypatch.setattr(api, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(api, "_require_auth", lambda: None)
    monkeypatch.setattr(api.web, "header", lambda *a, **kw: None)
    monkeypatch.setattr(api, "_read_config_file_for_write", lambda: copy.deepcopy(persisted))
    def save(path, value):
        persisted.clear()
        persisted.update(copy.deepcopy(value))
    monkeypatch.setattr(api, "_write_config_file_for_write", save)
    monkeypatch.setattr(api.sys, "platform", "win32")
    monkeypatch.setattr(api, "_shell_status", lambda: {"pwsh": {"available": True, "version": "7.5.0"}})
    return cfg, persisted


def post(monkeypatch, value):
    monkeypatch.setattr(api.web, "data", lambda: json.dumps(value).encode())
    return json.loads(api.BashSettingsHandler().POST())


def test_save_merges_nested_config_and_gets_effective_environment(settings, monkeypatch):
    cfg, persisted = settings
    result = post(monkeypatch, {"windows_shell": "pwsh"})
    assert result["status"] == "success"
    assert result["effective_shell"] == "pwsh"
    assert result["scope"] == "instance"
    assert persisted["tools"]["bash"] == {"timeout": 45, "windows_shell": "pwsh"}
    assert persisted["tools"]["read"] == {"other": True}
    assert cfg == persisted
    assert json.loads(api.BashSettingsHandler().GET())["windows_shell"] == "pwsh"


@pytest.mark.parametrize("value", [{"windows_shell": "powershell"}, [], {}, {"windows_shell": True}])
def test_invalid_shell_is_not_persisted(settings, monkeypatch, value):
    cfg, persisted = settings
    before = copy.deepcopy(cfg)
    assert post(monkeypatch, value)["status"] == "error"
    assert cfg == persisted == before


def test_missing_pwsh_rejected_but_cmd_can_be_restored(settings, monkeypatch):
    monkeypatch.setattr(api, "_shell_status", lambda: {"pwsh": {"available": False, "version": None}})
    assert post(monkeypatch, {"windows_shell": "pwsh"})["code"] == "pwsh_unavailable"
    assert post(monkeypatch, {"windows_shell": "cmd"})["status"] == "success"


def test_non_windows_host_rejects_windows_selection(settings, monkeypatch):
    monkeypatch.setattr(api.sys, "platform", "linux")
    monkeypatch.setattr(api, "_shell_status", lambda: pytest.fail("must not probe pwsh"))
    assert post(monkeypatch, {"windows_shell": "pwsh"})["code"] == "unsupported_platform"
    payload = json.loads(api.BashSettingsHandler().GET())
    assert payload["effective_shell"] == "sh"
    assert payload["pwsh"]["available"] is False


def test_failed_disk_write_leaves_live_configuration_untouched(settings, monkeypatch):
    cfg, persisted = settings
    before = copy.deepcopy(cfg)
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(api, "_write_config_file_for_write", fail)
    assert post(monkeypatch, {"windows_shell": "pwsh"})["code"] == "save_failed"
    assert cfg == persisted == before


def test_authentication_is_required(monkeypatch):
    def denied():
        raise PermissionError("authentication required")
    monkeypatch.setattr(api, "_require_auth", denied)
    with pytest.raises(PermissionError):
        api.BashSettingsHandler().GET()
    with pytest.raises(PermissionError):
        api.BashSettingsHandler().POST()
