"""What clearing the old roster out of ``config.json`` leaves behind.

``team.retire_legacy`` rewrites a live ``config.json`` — every API key, channel
credential and custom provider — straight through ``Path.write_text``, which
cuts the file short before the new bytes are there, so a write that stops
partway (full disk, container killed) leaves a partial file behind.
``load_config`` reads that as corruption: the desktop client quarantines it and
reinitialises from config-template.json, taking every key with it; a source
deployment raises and never starts. ``team.write``, twenty lines above and
writing the same kind of file, already saves through a sibling and swaps it in.
"""

import builtins
import errno
import io
import json
import os

from agent import team

LEGACY_ROSTER = {
    "agent_workspace": "/srv/cow",
    "agents": [{"id": "main", "name": "Main"}],
    "default_agent_id": "main",
    "channel_instances": [{"id": "weixin", "agent_id": "main"}],
}


def _an_existing_config(tmp_path):
    """A config.json still carrying the old roster, and the exact text of it."""
    path = tmp_path / "config.json"
    text = json.dumps(LEGACY_ROSTER, indent=4, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path, text


def _a_disk_that_fills_up(monkeypatch):
    """Every write-mode open gets half the document out, then reports ENOSPC.

    ``open``/``io.open`` cover the ``Path.write_text`` shape and ``os.fdopen`` the
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


def test_a_retire_that_fails_midway_keeps_the_previous_config(tmp_path, monkeypatch):
    path, original = _an_existing_config(tmp_path)
    _a_disk_that_fills_up(monkeypatch)

    team.retire_legacy(path)

    assert path.read_text(encoding="utf-8") == original, (
        "a half-finished tidy-up must not leave config.json cut short"
    )


def test_a_failed_retire_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    path, _ = _an_existing_config(tmp_path)
    _a_disk_that_fills_up(monkeypatch)

    team.retire_legacy(path)

    assert [p.name for p in tmp_path.iterdir() if p.name != "config.json"] == []


def test_a_retire_still_drops_the_roster_keys(tmp_path):
    path, _ = _an_existing_config(tmp_path)

    team.retire_legacy(path)

    remaining = json.loads(path.read_text(encoding="utf-8"))
    assert not any(key in remaining for key in team.TEAM_KEYS)
    assert remaining["agent_workspace"] == "/srv/cow"
