"""Web console one-click updater: local version metadata, GitHub-on-click, degrade."""

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.update_service import (
    UpdateError,
    apply_source_update,
    check_for_updates,
    compare_versions,
    detect_install_kind,
    parse_version,
    read_update_status,
    schedule_web_update,
    version_payload,
    write_update_status,
)


def test_parse_and_compare_versions():
    assert parse_version("v2.1.8") == (2, 1, 8)
    assert parse_version("2.1") == (2, 1, 0)
    assert parse_version("2.10.0") > parse_version("2.9.9")
    assert compare_versions("2.1.9", "2.1.8") == 1
    assert compare_versions("2.1.8", "v2.1.8") == 0
    assert compare_versions("2.1.7", "2.1.8") == -1


def test_git_checkout_is_supported_on_unix(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("COW_DESKTOP", raising=False)
    monkeypatch.delenv("COW_DOCKER", raising=False)
    monkeypatch.setattr("cli.update_service._is_docker_install", lambda: False)
    kind = detect_install_kind(str(tmp_path))
    assert kind.kind == "git"
    assert kind.update_supported is True


def test_windows_git_checkout_degrades(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("COW_DESKTOP", raising=False)
    monkeypatch.setattr("cli.update_service._is_docker_install", lambda: False)
    kind = detect_install_kind(str(tmp_path))
    assert kind.kind == "git"
    assert kind.update_supported is False
    assert "Windows" in kind.unsupported_reason


def test_docker_and_packaged_degrade(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("cli.update_service._is_docker_install", lambda: True)
    kind = detect_install_kind(str(tmp_path))
    assert kind.kind == "docker"
    assert kind.update_supported is False

    monkeypatch.setattr("cli.update_service._is_docker_install", lambda: False)
    monkeypatch.setenv("COW_DESKTOP", "1")
    kind = detect_install_kind(str(tmp_path))
    assert kind.kind == "packaged"
    assert kind.update_supported is False


def test_version_payload_does_not_call_github(monkeypatch):
    called = []

    def boom(*args, **kwargs):
        called.append(True)
        raise AssertionError("GitHub must not be contacted for /api/version")

    monkeypatch.setattr("cli.update_service.fetch_github_releases", boom)
    payload = version_payload()
    assert "version" in payload
    assert "install_kind" in payload
    assert "update_supported" in payload
    assert called == []


def test_check_for_updates_uses_github_and_filters(monkeypatch):
    monkeypatch.setattr(
        "cli.update_service.fetch_github_releases",
        lambda timeout=20: [
            {"tag_name": "2.1.9", "name": "2.1.9", "body": "newer", "html_url": "https://example/2.1.9", "published_at": "2026-09-14", "prerelease": False, "draft": False},
            {"tag_name": "2.1.8", "name": "2.1.8", "body": "current", "html_url": "https://example/2.1.8", "published_at": "2026-09-11", "prerelease": False, "draft": False},
            {"tag_name": "9.0.0", "name": "nightly", "body": "skip", "html_url": "", "published_at": "", "prerelease": True, "draft": False},
        ],
    )
    result = check_for_updates("2.1.8")
    assert result["up_to_date"] is False
    assert result["latest"]["tag"] == "2.1.9"
    assert [item["tag"] for item in result["newer_releases"]] == ["2.1.9"]
    assert result["current_release"]["tag"] == "2.1.8"


def test_check_up_to_date(monkeypatch):
    monkeypatch.setattr(
        "cli.update_service.fetch_github_releases",
        lambda timeout=20: [
            {"tag_name": "2.1.8", "name": "2.1.8", "body": "notes", "html_url": "u", "published_at": "", "prerelease": False, "draft": False},
        ],
    )
    result = check_for_updates("2.1.8")
    assert result["up_to_date"] is True
    assert result["newer_releases"] == []


def test_failed_pip_resets_git(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return types.SimpleNamespace(returncode=0, stdout="abc123\n")
        if cmd[:2] == ["git", "status"]:
            return types.SimpleNamespace(returncode=0, stdout="")
        if cmd[:2] == ["git", "pull"]:
            return types.SimpleNamespace(returncode=0, stdout="Already up to date.\n")
        if cmd[:2] == ["git", "reset"]:
            return types.SimpleNamespace(returncode=0, stdout="HEAD is now abc123\n")
        return types.SimpleNamespace(returncode=1, stdout="pip exploded\n")

    monkeypatch.setattr("cli.update_service._run", fake_run)
    monkeypatch.setattr("cli.update_service.os.path.exists", lambda path: True)
    with pytest.raises(UpdateError) as exc:
        apply_source_update(str(tmp_path), python="python", restore_sha="abc123")
    assert exc.value.step == "install_deps"
    assert ["git", "reset", "--hard", "abc123"] in calls


def test_local_edits_block_the_update_before_anything_runs(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd):
        calls.append(cmd)
        if cmd[:2] == ["git", "status"]:
            return types.SimpleNamespace(returncode=0, stdout=" M plugins/foo.py\n")
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("cli.update_service._run", fake_run)
    with pytest.raises(UpdateError) as exc:
        apply_source_update(str(tmp_path), python="python", restore_sha="abc123")
    assert exc.value.step == "git_pull"
    assert "plugins/foo.py" in exc.value.output
    assert not any(cmd[:2] in (["git", "pull"], ["git", "reset"]) for cmd in calls)


def test_the_console_pulls_fast_forward_only(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("cli.update_service._run", fake_run)
    monkeypatch.setattr("cli.update_service.os.path.exists", lambda path: False)
    apply_source_update(str(tmp_path), python="python", restore_sha="abc123")
    assert ["git", "pull", "--ff-only"] in calls


def test_a_running_status_left_by_a_dead_worker_does_not_block(tmp_path, monkeypatch):
    from cli import update_service

    monkeypatch.setattr(update_service, "_worker_alive", lambda pid: False)
    assert update_service._update_is_stale({"state": "running", "worker_pid": 4242}) is True

    monkeypatch.setattr(update_service, "_worker_alive", lambda pid: True)
    fresh = {"state": "running", "worker_pid": 4242, "started_at": update_service.datetime.now(
        update_service.timezone.utc).isoformat()}
    assert update_service._update_is_stale(fresh) is False
    assert update_service._update_is_stale(
        {"state": "running", "started_at": "2020-01-01T00:00:00+00:00"}
    ) is True


def test_web_handlers_auth_and_no_github_on_version(monkeypatch):
    if "web" not in sys.modules:
        web_stub = types.ModuleType("web")
        web_stub.HTTPError = type("HTTPError", (Exception,), {})
        web_stub.cookies = lambda: {}
        web_stub.header = lambda *args, **kwargs: None
        web_stub.data = lambda: b"{}"
        web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
        sys.modules["web"] = web_stub

    from channel.web.api import update as update_api

    monkeypatch.setattr(
        "cli.update_service.fetch_github_releases",
        lambda timeout=20: (_ for _ in ()).throw(AssertionError("no github on version")),
    )
    with patch("channel.web.api.update.web.header"):
        payload = json.loads(update_api.VersionHandler().GET())
    assert "version" in payload
    assert "update_supported" in payload

    with patch("channel.web.api.update._require_auth") as require_auth, \
         patch("channel.web.api.update.web.header"), \
         patch("cli.update_service.check_for_updates", return_value={"status": "success", "up_to_date": True, "newer_releases": [], "latest": None, "current_release": None, "current_version": "2.1.8"}):
        body = json.loads(update_api.UpdateCheckHandler().POST())
    require_auth.assert_called_once_with()
    assert body["status"] == "success"
    assert body["up_to_date"] is True

    with patch("channel.web.api.update._require_auth") as require_status, \
         patch("channel.web.api.update.web.header"), \
         patch("cli.update_service.read_update_status", return_value={"state": "idle"}):
        status = json.loads(update_api.UpdateStatusHandler().GET())
    require_status.assert_called_once_with()
    assert status["state"] == "idle"


def test_start_rejects_unsupported_install(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cli.update_service.detect_install_kind",
        lambda root=None: types.SimpleNamespace(
            kind="docker",
            update_supported=False,
            unsupported_reason="Docker installs are updated with docker compose",
            platform="linux",
        ),
    )
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(UpdateError) as exc:
        schedule_web_update(str(tmp_path))
    assert exc.value.step == "start"


def test_status_roundtrip(tmp_path):
    write_update_status({"state": "running", "step": "git_pull"}, root=str(tmp_path))
    data = read_update_status(str(tmp_path))
    assert data["state"] == "running"
    assert data["step"] == "git_pull"
    assert (tmp_path / "tmp" / "web-update-status.json").is_file()


def test_frontend_contract():
    root = Path(__file__).parents[1]
    # The page is assembled from templates/ and the scripts were split into a
    # core/ and views/ tree, so assert against what is actually served.
    from channel.web.core import template
    from conftest import console_js, web_backend_py

    html = template.render("chat.html")
    js = console_js()
    py = web_backend_py()
    assert 'id="update-menu"' in html
    assert 'id="sidebar-version"' in html
    assert 'id="update-dot"' in html
    assert "function toggleUpdateMenu" in js
    assert "function checkForConsoleUpdate" in js
    assert "function startConsoleUpdate" in js
    assert "/api/update/check" in js
    assert "/api/update/start" in js
    # Page load may read /api/version, but must not hit the GitHub check endpoint.
    load = js.split("function initApp()")[1].split("chatInput.focus")[0]
    assert "/api/update/check" not in load
    assert "'/api/update/check', 'UpdateCheckHandler'" in py
    assert "from cli.update_service import run_git_pull" in (
        root / "cli/commands/process.py"
    ).read_text(encoding="utf-8")
