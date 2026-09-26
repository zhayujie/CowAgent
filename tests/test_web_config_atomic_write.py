"""What a console save leaves behind when it cannot finish.

Every save reads config.json, changes a few keys and writes the whole dict back,
straight into the file — so the truncation that opens the write happens before
the new bytes are there. ``json.dump`` streams, so anything that goes wrong
partway through (a value it cannot encode, a full disk, the process being
killed) leaves a partial config.json behind.

Nothing here is a cache that could simply be rebuilt. The next ``load_config``
reads a partial file as corruption, and on the desktop client the self-heal path
quarantines it and replaces it with config-template.json, which takes every API
key, channel credential and custom provider with it; a source deployment instead
raises and never starts.

These tests pin the promise that a save either lands whole or leaves the previous
file exactly as it was.
"""

import errno
import importlib
import json

import pytest

ORIGINAL = {"agent_workspace": "/srv/cow", "web_password": "hunter2"}


def _an_existing_config(tmp_path):
    """A config.json already on disk, and the exact text it holds."""
    config_path = tmp_path / "config.json"
    text = json.dumps(ORIGINAL, indent=4, ensure_ascii=False)
    config_path.write_text(text, encoding="utf-8")
    return config_path, text


def _a_disk_that_fills_up_mid_write(obj, fp, **kwargs):
    """Stand-in for ``json.dump`` that gets part of the document out and only
    then reports ENOSPC, the way a real full disk behaves."""
    fp.write('{\n    "agent_workspace": "/srv/cow",\n    "web_password": "hun')
    fp.flush()
    raise OSError(errno.ENOSPC, "No space left on device")


def _the_write_helper():
    # Imported lazily so this module still collects against a tree that predates
    # the helper: the failure then comes from the missing name, not from an
    # import error that would take every test in the file down with it.
    return importlib.import_module("channel.web.core._common")


# ---------------------------------------------------------------------------
# The helper itself.
# ---------------------------------------------------------------------------

def test_a_save_that_cannot_serialise_keeps_the_previous_config(tmp_path):
    """``json.dump`` streams, so a value it cannot encode raises after the
    destination has already been opened and cut short."""
    config_path, original = _an_existing_config(tmp_path)

    with pytest.raises(TypeError):
        _the_write_helper()._write_config_file_for_write(
            str(config_path), {"web_password": "hunter2", "half": object()}
        )

    assert config_path.read_text(encoding="utf-8") == original


def test_a_save_that_fails_leaves_no_temp_file_behind(tmp_path):
    config_path, _ = _an_existing_config(tmp_path)

    with pytest.raises(TypeError):
        _the_write_helper()._write_config_file_for_write(str(config_path), {"half": object()})

    assert not (tmp_path / "config.json.tmp").exists()


def test_a_save_that_succeeds_replaces_the_file(tmp_path):
    config_path, _ = _an_existing_config(tmp_path)

    _the_write_helper()._write_config_file_for_write(
        str(config_path), {"web_password": "hunter2", "model": "gpt-4o"}
    )

    assert json.loads(config_path.read_text(encoding="utf-8"))["model"] == "gpt-4o"
    assert not (tmp_path / "config.json.tmp").exists()


# ---------------------------------------------------------------------------
# The three console entry points that share the helper.
# ---------------------------------------------------------------------------

def _console_save(tmp_path, monkeypatch, updates):
    """One real ``ConfigHandler.POST`` against a config.json inside tmp_path."""
    config_api = importlib.import_module("channel.web.api.config")
    config_path, original = _an_existing_config(tmp_path)
    live = dict(ORIGINAL)

    monkeypatch.setattr(config_api, "_require_auth", lambda: None)
    monkeypatch.setattr(config_api.web, "header", lambda *a, **k: None)
    monkeypatch.setattr(config_api.web, "data", lambda: json.dumps({"updates": updates}).encode())
    monkeypatch.setattr(config_api, "conf", lambda: live)
    monkeypatch.setattr(config_api, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(config_api, "_read_config_file_for_write", lambda: dict(live))

    return json.loads(config_api.ConfigHandler().POST()), config_path, original


def test_the_settings_page_keeps_the_previous_file_when_a_save_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(json, "dump", _a_disk_that_fills_up_mid_write)

    response, config_path, original = _console_save(tmp_path, monkeypatch, {"reasoning_effort": "high"})

    assert response["status"] == "error"
    assert config_path.read_text(encoding="utf-8") == original


def test_the_settings_page_still_saves_when_nothing_goes_wrong(tmp_path, monkeypatch):
    """The guard against a save that "cannot go wrong" because it never writes."""
    response, config_path, _ = _console_save(tmp_path, monkeypatch, {"reasoning_effort": "high"})

    assert response["status"] == "success"
    assert json.loads(config_path.read_text(encoding="utf-8"))["reasoning_effort"] == "high"


def test_a_channel_save_keeps_the_previous_file_when_a_save_fails(tmp_path, monkeypatch):
    channels_api = importlib.import_module("channel.web.api.channels")
    config_path, original = _an_existing_config(tmp_path)

    monkeypatch.setattr(channels_api, "conf", lambda: dict(ORIGINAL))
    monkeypatch.setattr(channels_api, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(channels_api, "_read_config_file_for_write", lambda: dict(ORIGINAL))
    monkeypatch.setattr(json, "dump", _a_disk_that_fills_up_mid_write)

    with pytest.raises(OSError):
        channels_api.ChannelsHandler()._handle_save("feishu", {"feishu_app_id": "cli_x"})

    assert config_path.read_text(encoding="utf-8") == original


def test_the_models_view_keeps_the_previous_file_when_a_save_fails(tmp_path, monkeypatch):
    models_api = importlib.import_module("channel.web.api.models")
    config_path, original = _an_existing_config(tmp_path)

    monkeypatch.setattr(models_api, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(json, "dump", _a_disk_that_fills_up_mid_write)

    with pytest.raises(OSError):
        models_api.ModelsHandler._write_file_config({"model": "gpt-4o"})

    assert config_path.read_text(encoding="utf-8") == original
