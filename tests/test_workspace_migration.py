"""The web console moves the workspace by scheduling it for the next start;
apply_pending carries it out before anything opens the workspace. Only the
workspace moves: config.json stays put and records the new place."""

import json
import os
import shutil
import sys

import pytest

import config as config_module
from common import workspace_migration as wm


def _link(target, link):
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(str(target), str(link), target_is_directory=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("COW_DATA_DIR", str(data))
    monkeypatch.delenv("AGENT_WORKSPACE", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    old = tmp_path / "old" / "cow"
    (old / "memory").mkdir(parents=True)
    (old / "memory" / "MEMORY.md").write_text("# mem", encoding="utf-8")
    (old / "agents" / "helper").mkdir(parents=True)
    (old / "agents" / "team.json").write_text(
        json.dumps({"agents": [{"id": "default"}, {"id": "helper", "workspace": str(old / "agents" / "helper")}]}),
        encoding="utf-8",
    )
    (data / "config.json").write_text(
        json.dumps({"model": "m", "agent_workspace": str(old)}), encoding="utf-8"
    )
    monkeypatch.setitem(config_module.conf(), "agent_workspace", str(old))
    return {"tmp": tmp_path, "data": data, "old": old, "home": home}


def _config(env):
    return json.loads((env["data"] / "config.json").read_text(encoding="utf-8"))


def test_a_scheduled_move_runs_on_the_next_start(env):
    parent = env["tmp"] / "new place"
    scheduled = wm.schedule(str(parent), keep_link=True)
    assert scheduled["ok"], scheduled
    target = parent / "cow"
    # Nothing moves while the service that holds the workspace is running.
    assert (env["old"] / "memory" / "MEMORY.md").is_file()
    assert wm.read_pending()["to"] == str(target)

    result = wm.apply_pending()

    assert result["ok"], result
    assert result["warnings"] == []
    assert (target / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "# mem"
    assert _config(env) == {"model": "m", "agent_workspace": str(target)}
    assert config_module.conf()["agent_workspace"] == str(target)
    team = json.loads((target / "agents" / "team.json").read_text(encoding="utf-8"))
    assert team["agents"][1]["workspace"] == str(target / "agents" / "helper")
    # The old path is a link, so absolute paths in past conversations resolve.
    assert wm._is_link(str(env["old"]))
    assert (env["old"] / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "# mem"
    assert wm.read_pending() is None
    assert wm.read_result()["ok"] is True
    assert wm.apply_pending() is None


def test_a_cross_device_move_copies_verifies_and_keeps_inner_links(env, monkeypatch):
    monkeypatch.setattr(wm, "_same_device", lambda a, b: False)
    external = env["tmp"] / "external-skill"
    external.mkdir()
    (external / "SKILL.md").write_text("external", encoding="utf-8")
    (env["old"] / "skills").mkdir()
    _link(external, env["old"] / "skills" / "linked")

    parent = env["tmp"] / "other"
    assert wm.schedule(str(parent), keep_link=False)["ok"]
    result = wm.apply_pending()

    target = parent / "cow"
    assert result["ok"], result
    assert wm._is_link(str(target / "skills" / "linked"))
    assert (target / "skills" / "linked" / "SKILL.md").read_text(encoding="utf-8") == "external"
    assert (external / "SKILL.md").is_file(), "removing the old workspace must not follow its links"
    assert not os.path.lexists(env["old"]), "no link was asked for"


def test_a_failed_copy_leaves_everything_as_it_was(env, monkeypatch):
    monkeypatch.setattr(wm, "_same_device", lambda a, b: False)
    real_copy = shutil.copy2

    def flaky(src, dst, *args, **kwargs):
        if os.path.basename(src) == "MEMORY.md":
            raise PermissionError("in use")
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(wm.shutil, "copy2", flaky)
    parent = env["tmp"] / "other"
    assert wm.schedule(str(parent), keep_link=True)["ok"]
    before = (env["data"] / "config.json").read_text(encoding="utf-8")

    result = wm.apply_pending()

    assert result["ok"] is False
    assert result["code"] == "copy_failed"
    assert "in use" in result["detail"]
    assert not (parent / "cow").exists()
    assert (env["old"] / "memory" / "MEMORY.md").is_file()
    assert (env["data"] / "config.json").read_text(encoding="utf-8") == before
    assert config_module.conf()["agent_workspace"] == str(env["old"])
    assert wm.read_pending() is None, "a failed move must not retry on every start"


def test_ctrl_c_during_the_copy_leaves_nothing_behind(env, monkeypatch):
    monkeypatch.setattr(wm, "_same_device", lambda a, b: False)
    real_copy = shutil.copy2

    def interrupted(src, dst, *args, **kwargs):
        if os.path.basename(src) == "MEMORY.md":
            raise KeyboardInterrupt
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(wm.shutil, "copy2", interrupted)
    parent = env["tmp"] / "other"
    assert wm.schedule(str(parent), keep_link=True)["ok"]

    with pytest.raises(KeyboardInterrupt):
        wm.apply_pending()

    assert not (parent / "cow").exists()
    assert (env["old"] / "memory" / "MEMORY.md").is_file()
    assert _config(env)["agent_workspace"] == str(env["old"])
    # The next start tells the console why the move didn't happen.
    assert wm.read_result()["code"] == "interrupted"


def test_a_killed_copy_can_be_moved_over(env):
    stale = env["tmp"] / "stale" / "cow"
    (stale / "memory").mkdir(parents=True)
    (stale / wm._INCOMPLETE_MARKER).write_text("", encoding="utf-8")

    check = wm.check_target(str(stale.parent))
    assert check["ok"], check

    assert wm.schedule(str(stale.parent), keep_link=True)["ok"]
    result = wm.apply_pending()
    assert result["ok"], result
    assert (stale / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "# mem"
    assert not (stale / wm._INCOMPLETE_MARKER).exists()


def test_the_console_port_reports_progress_while_the_move_runs(env):
    import socket
    import urllib.error
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    wm._state.clear()
    wm._Progress(10, 1000).add(250)

    stop = wm.serve_progress("127.0.0.1", port)
    assert stop is not None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/workspace-location") as resp:
            info = json.loads(resp.read())
        assert info["migrating"] is True
        assert info["progress"] == {"phase": "copying", "done_files": 1, "total_files": 10,
                                    "done_bytes": 250, "total_bytes": 1000}
        with pytest.raises(urllib.error.HTTPError) as page:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/settings")
        assert page.value.code == 503
    finally:
        stop()

    # The console binds the same port right after.
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_config_and_code_stay_out_of_the_workspace(env):
    assert wm.check_target(str(env["data"]))["code"] == "protected_dir"
    assert wm.check_target(str(env["home"] / ".cow"))["code"] == "protected_dir"
    assert wm.check_target(config_module.get_root())["code"] == "protected_dir"


def test_refusals(env):
    assert wm.check_target(str(env["old"].parent))["code"] == "same_location"
    assert wm.check_target("relative/dir")["code"] == "not_absolute"
    assert wm.check_target(str(env["old"] / "sub"))["code"] == "nested"
    occupied = env["tmp"] / "occupied"
    (occupied / "cow").mkdir(parents=True)
    (occupied / "cow" / "x.txt").write_text("x", encoding="utf-8")
    assert wm.check_target(str(occupied))["code"] == "target_has_data"


def test_windows_needs_python_38_to_tell_junctions_from_folders(env, monkeypatch):
    assert wm.schedule(str(env["tmp"] / "other"), keep_link=True)["ok"]
    monkeypatch.setattr(wm, "links_supported", lambda: False)

    result = wm.apply_pending()

    assert result["code"] == "python_too_old"
    assert (env["old"] / "memory" / "MEMORY.md").is_file()


def test_a_workspace_changed_since_scheduling_is_not_moved(env, monkeypatch):
    assert wm.schedule(str(env["tmp"] / "other"), keep_link=True)["ok"]
    elsewhere = env["tmp"] / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setitem(config_module.conf(), "agent_workspace", str(elsewhere))

    result = wm.apply_pending()

    assert result["ok"] is False
    assert result["code"] == "workspace_changed"
    assert (env["old"] / "memory" / "MEMORY.md").is_file()


def test_a_workspace_moved_by_the_other_client_shows_where_it_went(env, monkeypatch):
    moved = env["tmp"] / "moved" / "cow"
    moved.parent.mkdir()
    shutil.move(str(env["old"]), str(moved))
    _link(moved, env["old"])

    assert wm.current_workspace() == str(env["old"])
    assert wm._norm(wm.real_workspace()) == wm._norm(str(moved))
    assert wm.workspace_size() == len("# mem") + (moved / "agents" / "team.json").stat().st_size
    # Picking the place it is shown at is not a move into itself.
    assert wm.check_target(str(moved.parent))["code"] == "same_location"

    plain = env["tmp"] / "plain"
    plain.mkdir()
    monkeypatch.setitem(config_module.conf(), "agent_workspace", str(plain))
    assert wm.real_workspace() == str(plain)


def test_moving_a_workspace_reached_through_a_link_keeps_the_link_working(env):
    moved = env["tmp"] / "moved" / "cow"
    moved.parent.mkdir()
    shutil.move(str(env["old"]), str(moved))
    _link(moved, env["old"])
    parent = env["tmp"] / "again"

    assert wm.schedule(str(parent), keep_link=True)["ok"]
    result = wm.apply_pending()

    assert result["ok"], result
    target = parent / "cow"
    assert (target / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "# mem"
    assert not moved.exists()
    assert wm._is_link(str(env["old"]))
    assert wm._norm(wm._realpath(str(env["old"]))) == wm._norm(str(target))
    assert _config(env)["agent_workspace"] == str(target)


def test_an_env_override_locks_the_location(env, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(env["old"]))
    assert wm.check_target(str(env["tmp"] / "other"))["code"] == "managed_by_env"
