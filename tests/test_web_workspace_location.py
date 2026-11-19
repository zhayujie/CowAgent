"""/api/workspace-location only points the Agent at another folder for someone
who could already reach that folder: the desktop shell has its own card, and an
open console only accepts it from the machine itself."""

import json
import os
import subprocess
import sys
import time
import types

import pytest

from channel.web.api import workspace_location as api
from common import workspace_migration as wm


def _post(monkeypatch, body):
    monkeypatch.setattr(api, "web", types.SimpleNamespace(
        header=lambda *a, **k: None,
        data=lambda: json.dumps(body).encode(),
        input=lambda **k: types.SimpleNamespace(**k),
    ))
    return json.loads(api.WorkspaceLocationHandler().POST())


@pytest.fixture
def scheduled(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "_require_auth", lambda: None)
    monkeypatch.delenv("COW_DESKTOP", raising=False)
    monkeypatch.setattr("cli.update_service._is_docker_install", lambda: False)
    monkeypatch.setattr(api.wm, "managed_by_env", lambda: False)
    monkeypatch.setattr(api.wm, "schedule", lambda *a: calls.append(a) or {"ok": True})
    monkeypatch.setattr(api.wm, "read_pending", lambda: None)
    monkeypatch.setattr(api.wm, "read_result", lambda: None)
    return calls


def test_an_open_console_only_moves_the_workspace_from_this_machine(monkeypatch, scheduled):
    monkeypatch.setattr(api, "_is_password_enabled", lambda: False)
    monkeypatch.setattr(api, "_is_loopback_request", lambda: False)
    reply = _post(monkeypatch, {"action": "schedule", "parent": "D:\\data"})
    assert reply == {"status": "error", "code": "remote_without_password"}
    assert scheduled == []

    monkeypatch.setattr(api, "_is_loopback_request", lambda: True)
    reply = _post(monkeypatch, {"action": "schedule", "parent": "D:\\data"})
    assert reply["status"] == "success"
    assert scheduled == [("D:\\data", True)]


def test_a_password_protected_console_accepts_it_remotely(monkeypatch, scheduled):
    monkeypatch.setattr(api, "_is_password_enabled", lambda: True)
    monkeypatch.setattr(api, "_is_loopback_request", lambda: False)
    reply = _post(monkeypatch, {"action": "schedule", "parent": "/srv", "keep_link": False})
    assert reply["status"] == "success"
    assert scheduled == [("/srv", False)]


def test_the_terminal_channel_restarts_by_hand(monkeypatch):
    monkeypatch.setattr(api.sys, "argv", ["app.py"])
    assert api._restart_mode() == "auto"
    monkeypatch.setattr(api.sys, "argv", ["app.py", "--cmd"])
    assert api._restart_mode() == "manual"


def test_windows_on_python_37_cannot_move_it(monkeypatch, scheduled):
    monkeypatch.setattr(api, "_is_password_enabled", lambda: True)
    monkeypatch.setattr(api.wm, "links_supported", lambda: False)
    assert _post(monkeypatch, {"action": "schedule", "parent": "/srv"})["code"] == "python_too_old"
    assert scheduled == []


def test_the_desktop_shell_keeps_its_own_card(monkeypatch, scheduled):
    monkeypatch.setenv("COW_DESKTOP", "1")
    monkeypatch.setattr(api, "_is_password_enabled", lambda: True)
    assert _post(monkeypatch, {"action": "schedule", "parent": "/srv"})["code"] == "desktop"
    assert scheduled == []


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows relay")
@pytest.mark.parametrize("background", [False, True])
def test_the_windows_relay_starts_the_service_once_the_old_one_is_gone(tmp_path, background):
    marker = tmp_path / "started.txt"
    app_py = tmp_path / "app.py"
    app_py.write_text(
        "import os, sys\n"
        f"open({str(marker)!r}, 'w').write(' '.join(sys.argv[1:]) + ' ' + str(os.getpid()))\n",
        encoding="utf-8",
    )
    old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    log_file = tmp_path / "run.log"
    pid_file = tmp_path / "cow.pid"
    relay = subprocess.run(
        [sys.executable, "-c", api._WIN_RELAY_SCRIPT, sys.executable, str(app_py), str(tmp_path),
         str(old.pid), str(log_file) if background else "", str(pid_file), "--cmd"],
        timeout=60,
    )

    assert old.poll() is not None, "the new service waits for the old one"
    assert relay.returncode == 0
    for _ in range(50):
        if marker.exists() and marker.read_text():
            break
        time.sleep(0.1)
    args, _ = marker.read_text().rsplit(" ", 1)
    assert args == "--cmd"
    if background:
        # A venv python.exe is a launcher, so the recorded pid may be its parent.
        assert pid_file.read_text().isdigit()
    else:
        assert not pid_file.exists()


def test_restart_needs_a_scheduled_move(monkeypatch, scheduled):
    monkeypatch.setattr(api, "_is_password_enabled", lambda: True)
    started = []
    monkeypatch.setattr(api, "_restart_service", lambda: started.append(True))
    assert _post(monkeypatch, {"action": "restart"})["code"] == "nothing_pending"

    monkeypatch.setattr(api.wm, "read_pending", lambda: {"to": "/srv/cow"})
    monkeypatch.setattr(api, "_restart_mode", lambda: "manual")
    assert _post(monkeypatch, {"action": "restart"})["code"] == "restart_unsupported"
    monkeypatch.setattr(api, "_restart_mode", lambda: "auto")
    assert _post(monkeypatch, {"action": "restart"})["status"] == "success"
    assert started == [True]


def test_the_native_dialog_only_opens_in_front_of_the_person_asking(monkeypatch, scheduled):
    monkeypatch.setattr(api, "_is_password_enabled", lambda: True)
    opened = []
    monkeypatch.setattr(api, "_native_pick_folder", lambda title, start: opened.append(title) or "D:\\data")
    monkeypatch.setattr(api.wm, "current_workspace", lambda: "C:\\Users\\me\\cow")

    monkeypatch.setattr(api, "_can_reveal_in_file_manager", lambda: False)
    assert _post(monkeypatch, {"action": "pick", "title": "t"})["code"] == "pick_unsupported"
    assert opened == []

    monkeypatch.setattr(api, "_can_reveal_in_file_manager", lambda: True)
    assert _post(monkeypatch, {"action": "pick", "title": "t"}) == {"status": "success", "path": "D:\\data"}
    assert opened == ["t"]


def test_a_dialog_that_cannot_open_falls_through_to_the_next(monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd[0])
        if len(calls) == 1:
            raise FileNotFoundError(cmd[0])
        return types.SimpleNamespace(returncode=0, stdout="D:/新建文件夹".encode("utf-8"), stderr=b"")

    monkeypatch.setattr(api, "_pick_commands", lambda title, start: [(["missing"], ()), (["works"], ())])
    monkeypatch.setattr(api.subprocess, "run", run)
    assert api._native_pick_folder("t", "") == os.path.normpath("D:/新建文件夹")
    assert calls == ["missing", "works"]


def test_a_cancelled_dialog_is_not_a_missing_one(monkeypatch):
    monkeypatch.setattr(api, "_pick_commands", lambda title, start: [(["zenity"], (1,)), (["tk"], ())])
    monkeypatch.setattr(api.subprocess, "run",
                        lambda cmd, **k: types.SimpleNamespace(returncode=1, stdout=b"", stderr=b""))
    assert api._native_pick_folder("t", "") == ""

    monkeypatch.setattr(api, "_pick_commands", lambda title, start: [(["a"], ()), (["b"], ())])
    monkeypatch.setattr(api.subprocess, "run",
                        lambda cmd, **k: types.SimpleNamespace(returncode=2, stdout=b"", stderr=b"no display"))
    assert api._native_pick_folder("t", "") is None


def test_the_route_is_registered():
    from channel.web import web_channel

    source = open(web_channel.__file__, encoding="utf-8").read()
    assert "'/api/workspace-location', 'WorkspaceLocationHandler'" in source
    assert wm.pending_path().endswith("workspace-migration.json")
