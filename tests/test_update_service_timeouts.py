"""Every subprocess the web one-click update runs has to be bounded.

``cli.update_service._run`` executes every step of a web one-click update:
git rev-parse / status / pull / reset, both pip installs and the
``import app`` self-check. A stalled step (a hung network during git pull, a
mirror that trickles during pip) left the update worker alive with the status
file stuck mid-update forever - and once STALE_UPDATE_SECONDS lets a second
update start, both work on the same checkout. Callers only branch on
``returncode`` and read ``stdout``, so a timed-out step reports as a failed
one and flows into the existing git_reset_hard rollback.
"""

import subprocess

import pytest

from cli import update_service


def test_run_synthesizes_a_failed_process_on_timeout(monkeypatch):
    def hung(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"], output=b"partial output")

    monkeypatch.setattr(update_service.subprocess, "run", hung)
    proc = update_service._run(["git", "pull"], cwd=".")
    assert proc.returncode != 0
    assert "partial output" in proc.stdout
    assert "timed out" in proc.stdout


def test_a_timed_out_install_raises_update_error_and_rolls_back(tmp_path, monkeypatch):
    rolled_back = []
    monkeypatch.setattr(update_service, "git_rev_parse", lambda root: "abc123")

    def stalled_install(root, python, quiet=False):
        return subprocess.CompletedProcess(args=["pip"], returncode=-1, stdout="timed out")

    monkeypatch.setattr(update_service, "git_tracked_changes", lambda root: "")
    monkeypatch.setattr(
        update_service, "run_git_pull",
        lambda root, ff_only=False: subprocess.CompletedProcess(args=["git"], returncode=0, stdout=""),
    )
    monkeypatch.setattr(update_service, "install_requirements", stalled_install)
    monkeypatch.setattr(update_service, "git_reset_hard", lambda root, sha: rolled_back.append(sha))

    with pytest.raises(update_service.UpdateError) as excinfo:
        update_service.apply_source_update(str(tmp_path))
    assert excinfo.value.step == "install_deps"
    assert rolled_back == ["abc123"], "a timed-out step must land in the existing rollback"


def test_pip_steps_get_the_longer_ceiling(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="")

    monkeypatch.setattr(update_service.subprocess, "run", fake_run)
    update_service.install_requirements(".", "python")
    update_service.install_editable(".", "python")
    assert seen.get("timeout") == update_service._PIP_TIMEOUT_S, \
        "pip installs ran without the dependency ceiling"


def test_self_check_gets_the_import_ceiling(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="")

    monkeypatch.setattr(update_service.subprocess, "run", fake_run)
    update_service.self_check_app(".", "python")
    assert seen.get("timeout") == update_service._IMPORT_TIMEOUT_S, \
        "the import self-check ran without the import ceiling"


def test_a_healthy_run_passes_through_unchanged(tmp_path):
    proc = update_service._run(["python", "-c", "print('ok')"], cwd=str(tmp_path), timeout=30)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "ok"
