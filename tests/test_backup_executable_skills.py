"""A portable workspace backup must keep skill entrypoints runnable."""
import os
import stat
import subprocess
import zipfile

import pytest

from cli.commands.backup import create_backup_archive, restore_backup_archive


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable permissions")
@pytest.mark.parametrize("mode", [0o700, 0o750, 0o755])
def test_round_trip_keeps_skill_entrypoint_executable(tmp_path, mode):
    workspace = tmp_path / "source-workspace"
    script = workspace / "skills" / "report" / "scripts" / "run.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nprintf 'skill restored\\n'\n", encoding="utf-8")
    script.chmod(mode)
    archive = tmp_path / "backup.zip"
    create_backup_archive(archive, tmp_path / "data", workspace)
    with zipfile.ZipFile(archive) as bundle:
        assert stat.S_IMODE(bundle.getinfo("workspace/skills/report/scripts/run.sh").external_attr >> 16) == mode
    target = tmp_path / "restored"
    restore_backup_archive(archive, tmp_path / "restored-data", target)
    restored = target / script.relative_to(workspace)
    # A real launch, rather than checking only a mode integer, is the user oracle.
    result = subprocess.run([str(restored)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "skill restored\n"
    assert stat.S_IMODE(restored.stat().st_mode) == mode


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_round_trip_retains_plain_file_mode_without_making_it_executable(tmp_path):
    workspace = tmp_path / "source-workspace"
    workspace.mkdir()
    note = workspace / "MEMORY.md"
    note.write_text("remember this\n", encoding="utf-8")
    note.chmod(0o600)
    archive = tmp_path / "backup.zip"
    create_backup_archive(archive, tmp_path / "data", workspace)
    target = tmp_path / "restored"
    restore_backup_archive(archive, tmp_path / "restored-data", target)
    restored = target / "MEMORY.md"
    assert restored.read_bytes() == note.read_bytes()
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
@pytest.mark.parametrize("create_system,unix_mode", [(0, 0), (3, stat.S_IFREG)])
def test_legacy_archives_without_permissions_keep_usable_defaults(tmp_path, create_system, unix_mode):
    import json
    archive = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"format": "cowagent-backup", "version": 1}))
        info = zipfile.ZipInfo("workspace/MEMORY.md")
        info.create_system = create_system
        # A DOS attribute keeps ZipFile from synthesizing a default Unix mode.
        info.external_attr = (unix_mode << 16) | 0x20
        bundle.writestr(info, "legacy notes\n")
    target = tmp_path / "restored"
    restore_backup_archive(archive, tmp_path / "data", target)
    restored = target / "MEMORY.md"
    assert restored.read_text() == "legacy notes\n"
    assert restored.stat().st_mode & stat.S_IRUSR
    assert not restored.stat().st_mode & 0o111


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_special_mode_bits_are_not_restored_and_config_stays_private(tmp_path):
    import json
    workspace = tmp_path / "source-workspace"
    workspace.mkdir()
    script = workspace / "run.sh"
    script.write_text("#!/bin/sh\nprintf 'safe skill\\n'\n")
    script.chmod(0o755)
    data = tmp_path / "source-data"
    data.mkdir()
    (data / "config.json").write_text(json.dumps({"agent_workspace": str(workspace)}))
    archive = tmp_path / "backup.zip"
    create_backup_archive(archive, data, workspace)
    # Mark archive entries, rather than setting special bits on a live fixture.
    modified = tmp_path / "modified.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(modified, "w") as output:
        for info in source.infolist():
            if info.filename == "workspace/run.sh":
                info.external_attr = (stat.S_IFREG | 0o7755) << 16
            if info.filename == "data/config.json":
                info.external_attr = (stat.S_IFREG | 0o777) << 16
            output.writestr(info, source.read(info.filename))
    target = tmp_path / "restored"
    target_data = tmp_path / "restored-data"
    restore_backup_archive(modified, target_data, target)
    assert stat.S_IMODE((target / "run.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((target_data / "config.json").stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
@pytest.mark.parametrize("mode", [0o111, 0o200])
@pytest.mark.parametrize("include_config", [False, True])
def test_unreadable_archived_modes_are_applied_only_after_copying(tmp_path, mode, include_config):
    import json
    archive = tmp_path / "external.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"format": "cowagent-backup", "version": 1}))
        for name, text in [("workspace/skills/run.sh", "#!/bin/sh\nexit 0\n"),
                           ("data/config.json", json.dumps({"agent_workspace": "/old"}))]:
            if name == "data/config.json" and not include_config:
                continue
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            bundle.writestr(info, text)
    target = tmp_path / "restored"
    data = tmp_path / "data"
    try:
        restore_backup_archive(archive, data, target)
        script = target / "skills" / "run.sh"
        assert stat.S_IMODE(script.stat().st_mode) == mode
        if include_config:
            assert stat.S_IMODE((data / "config.json").stat().st_mode) == 0o600
            assert json.loads((data / "config.json").read_text())["agent_workspace"] == str(target.resolve())
        # Inspect content only after restoring owner read permission for the test.
        script.chmod(0o600)
        assert script.read_text() == "#!/bin/sh\nexit 0\n"
    finally:
        # Keep pytest's fixture cleanup independent of intentionally denied modes.
        for path in target.rglob("*") if target.exists() else []:
            if path.is_file():
                path.chmod(0o600)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_mode_publication_failure_keeps_old_file_and_config(tmp_path, monkeypatch):
    import json
    from cli.commands import backup
    workspace = tmp_path / "source"
    workspace.mkdir()
    script = workspace / "run.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    archive = tmp_path / "backup.zip"
    create_backup_archive(archive, tmp_path / "source-data", workspace)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "run.sh").write_text("old script")
    data = tmp_path / "data"
    data.mkdir()
    saved_config = json.dumps({"agent_workspace": str(target), "model": "keep-me"})
    (data / "config.json").write_text(saved_config)
    real_chmod = os.chmod

    def fail_mode_publish(path, mode, *args, **kwargs):
        if os.path.basename(path).startswith("run.sh.") and mode == 0o755:
            raise PermissionError("mode cannot be applied")
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(backup.os, "chmod", fail_mode_publish)
    with pytest.raises(PermissionError, match="mode cannot be applied"):
        restore_backup_archive(archive, data, target)
    assert (target / "run.sh").read_text() == "old script"
    assert (data / "config.json").read_text() == saved_config
    assert sorted(p.name for p in target.iterdir()) == ["run.sh"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_multi_agent_round_trip_preserves_each_workspace_mode(tmp_path):
    import json
    data = tmp_path / "source-data"
    data.mkdir()
    primary, worker = tmp_path / "primary", tmp_path / "worker"
    for workspace, mode in [(primary, 0o700), (worker, 0o750)]:
        workspace.mkdir()
        script = workspace / "run.sh"
        script.write_text("#!/bin/sh\nprintf 'agent skill\\n'\n")
        script.chmod(mode)
    (data / "config.json").write_text(json.dumps({
        "agent_workspace": str(primary), "default_agent_id": "primary",
        "agents": [{"id": "primary", "workspace": str(primary)},
                   {"id": "worker", "workspace": str(worker)}],
    }))
    archive = tmp_path / "multi.zip"
    create_backup_archive(archive, data, primary)
    target = tmp_path / "restored"
    restored = restore_backup_archive(archive, tmp_path / "restored-data", target)
    roots = {agent["id"]: agent["workspace"] for agent in restored["agents"]}
    from pathlib import Path
    for agent_id, mode in [("primary", 0o700), ("worker", 0o750)]:
        script = Path(roots[agent_id]) / "run.sh"
        assert stat.S_IMODE(script.stat().st_mode) == mode
        assert subprocess.check_output([str(script)], timeout=5) == b"agent skill\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_duplicate_entry_uses_last_payload_and_its_metadata(tmp_path):
    import json
    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"format": "cowagent-backup", "version": 1}))
        first = zipfile.ZipInfo("workspace/note.txt")
        first.create_system = 3
        first.external_attr = (stat.S_IFREG | 0o755) << 16
        bundle.writestr(first, "first payload")
        last = zipfile.ZipInfo(first.filename)
        last.create_system = 0
        last.external_attr = 0x20
        with pytest.warns(UserWarning, match="Duplicate name"):
            bundle.writestr(last, "last payload")
    target = tmp_path / "restored"
    restore_backup_archive(archive, tmp_path / "data", target)
    note = target / "note.txt"
    assert note.read_text() == "last payload"
    assert note.stat().st_mode & stat.S_IRUSR
    assert not note.stat().st_mode & 0o111
