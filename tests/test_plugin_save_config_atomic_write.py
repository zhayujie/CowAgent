"""What a plugin save leaves behind when it cannot finish.

``Plugin.save_config`` writes both copies of a plugin's configuration — the
managed ``./plugins/config.json`` and the one next to the plugin — straight into
the destination with ``open(..., "w")``, which cuts the file short before the
new bytes are there. A save that stops part-way (a full disk, an update
interrupted) therefore leaves a half-written store behind.

``PluginManager._load_all_config`` reads ``plugins/config.json`` with a bare
``json.load`` whose failure is only logged, so the damage is silent: every
plugin loses its configuration at once — the godcmd password and admin list, the
keyword entries, the LinkAI binding — and nothing tells the user. It is the same
store and the same shape that ``PluginManager.save_config`` was given a sibling
file and ``os.replace`` for.
"""

import builtins
import errno
import io
import json
import os

from plugins.plugin import Plugin

EXISTING_GLOBAL = {"godcmd": {"password": "secret", "admin_users": ["alice"]}}
EXISTING_PLUGIN = {"password": "secret"}


def _an_installed_plugin(tmp_path, monkeypatch):
    """A plugin whose both config files are already on disk, and their text."""
    global_path = tmp_path / "plugins" / "config.json"
    global_path.parent.mkdir(parents=True)
    global_text = json.dumps(EXISTING_GLOBAL, indent=4, ensure_ascii=False)
    global_path.write_text(global_text, encoding="utf-8")

    plugin_dir = tmp_path / "godcmd"
    plugin_dir.mkdir()
    plugin_path = plugin_dir / "config.json"
    plugin_text = json.dumps(EXISTING_PLUGIN, indent=4, ensure_ascii=False)
    plugin_path.write_text(plugin_text, encoding="utf-8")

    monkeypatch.chdir(tmp_path)  # save_config writes "./plugins/config.json"
    plugin = Plugin()
    plugin.name = "godcmd"
    plugin.path = str(plugin_dir)
    return plugin, (global_path, global_text), (plugin_path, plugin_text)


def _a_disk_that_fills_up(monkeypatch):
    """Every write-mode open gets half the document out, then reports ENOSPC.

    ``open``/``io.open`` cover the plain ``open(..., "w")`` shape and ``os.fdopen`` the
    descriptor one, so the injection follows whichever the writer uses.
    """

    def _sabotaged(handle):
        def write(text):
            handle_write(text[: len(text) // 2])
            handle.flush()
            raise OSError(errno.ENOSPC, "No space left on device")

        handle_write = handle.write
        handle.write = write
        return handle

    real_open, real_fdopen = io.open, os.fdopen

    def open_for_write(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return _sabotaged(handle) if "w" in mode and "config.json" in str(file) else handle

    def fdopen(fd, mode="r", *args, **kwargs):
        handle = real_fdopen(fd, mode, *args, **kwargs)
        return _sabotaged(handle) if "w" in mode else handle

    monkeypatch.setattr(io, "open", open_for_write)
    monkeypatch.setattr(builtins, "open", open_for_write)
    monkeypatch.setattr(os, "fdopen", fdopen)


def test_a_save_that_fails_midway_keeps_the_previous_config(tmp_path, monkeypatch):
    plugin, (global_path, global_text), (plugin_path, plugin_text) = _an_installed_plugin(tmp_path, monkeypatch)
    _a_disk_that_fills_up(monkeypatch)

    plugin.save_config({"password": "rotated"})

    assert global_path.read_text(encoding="utf-8") == global_text
    assert plugin_path.read_text(encoding="utf-8") == plugin_text


def test_a_failed_save_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    plugin, (global_path, _), _ = _an_installed_plugin(tmp_path, monkeypatch)
    _a_disk_that_fills_up(monkeypatch)

    plugin.save_config({"password": "rotated"})

    assert [p.name for p in global_path.parent.iterdir() if p.name != "config.json"] == []


def test_a_save_still_writes_both_copies(tmp_path, monkeypatch):
    plugin, (global_path, _), (plugin_path, _) = _an_installed_plugin(tmp_path, monkeypatch)

    plugin.save_config({"password": "rotated"})

    assert json.loads(global_path.read_text(encoding="utf-8"))["godcmd"]["password"] == "rotated"
    assert json.loads(plugin_path.read_text(encoding="utf-8"))["password"] == "rotated"
