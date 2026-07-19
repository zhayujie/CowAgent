"""Tests for portable CowAgent backup archives."""

import json
import zipfile
from pathlib import Path

import pytest

from cli.commands.backup import create_backup_archive, restore_backup_archive


def _write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_backup_restore_round_trip(tmp_path):
    source_data = tmp_path / "source-data"
    source_workspace = tmp_path / "source-workspace"
    _write_json(source_data / "config.json", {
        "agent_workspace": str(source_workspace),
        "open_ai_api_key": "secret-value",
    })
    (source_workspace / "memory").mkdir(parents=True)
    (source_workspace / "scheduler").mkdir()
    (source_workspace / "knowledge").mkdir()
    (source_workspace / "USER.md").write_text("# User\n", encoding="utf-8")
    (source_workspace / "MEMORY.md").write_text("remember this\n", encoding="utf-8")
    (source_workspace / "memory" / "2026-07-17.md").write_text("daily\n", encoding="utf-8")
    (source_workspace / "scheduler" / "tasks.json").write_text("{}\n", encoding="utf-8")
    (source_workspace / "knowledge" / "index.md").write_text("# Index\n", encoding="utf-8")
    (source_workspace / "tmp").mkdir()
    (source_workspace / "tmp" / "scratch.txt").write_text("skip", encoding="utf-8")

    archive = tmp_path / "cow-backup.zip"
    summary = create_backup_archive(archive, source_data, source_workspace)
    assert summary["contents"]["workspace_files"] == 5
    assert archive.exists()

    target_data = tmp_path / "target-data"
    target_workspace = tmp_path / "target-workspace"
    result = restore_backup_archive(archive, target_data, target_workspace)

    restored_config = json.loads((target_data / "config.json").read_text(encoding="utf-8"))
    assert restored_config["agent_workspace"] == str(target_workspace.resolve())
    assert restored_config["open_ai_api_key"] == "secret-value"
    assert (target_workspace / "MEMORY.md").read_text(encoding="utf-8") == "remember this\n"
    assert (target_workspace / "scheduler" / "tasks.json").exists()
    assert (target_workspace / "knowledge" / "index.md").exists()
    assert not (target_workspace / "tmp" / "scratch.txt").exists()
    assert result["workspace_files"] == 5


def test_restore_merges_without_deleting_unrelated_files(tmp_path):
    source_data = tmp_path / "source-data"
    source_workspace = tmp_path / "source-workspace"
    _write_json(source_data / "config.json", {"agent_workspace": str(source_workspace)})
    source_workspace.mkdir()
    (source_workspace / "MEMORY.md").write_text("new\n", encoding="utf-8")
    archive = tmp_path / "cow-backup.zip"
    create_backup_archive(archive, source_data, source_workspace)

    target_workspace = tmp_path / "target-workspace"
    target_workspace.mkdir()
    (target_workspace / "MEMORY.md").write_text("old\n", encoding="utf-8")
    (target_workspace / "keep.txt").write_text("keep\n", encoding="utf-8")

    restore_backup_archive(archive, tmp_path / "target-data", target_workspace)
    assert (target_workspace / "MEMORY.md").read_text(encoding="utf-8") == "new\n"
    assert (target_workspace / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_restore_rejects_path_traversal(tmp_path):
    archive = tmp_path / "malicious.zip"
    manifest = {"format": "cowagent-backup", "version": 1}
    with zipfile.ZipFile(str(archive), "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr("workspace/../../escape.txt", "nope")

    with pytest.raises(ValueError, match="unsafe archive path"):
        restore_backup_archive(archive, tmp_path / "data", tmp_path / "workspace")


def test_restore_accepts_legacy_version_one_archive(tmp_path):
    archive = tmp_path / "legacy.zip"
    manifest = {"format": "cowagent-backup", "version": 1}
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr(
            "data/config.json", json.dumps({"agent_workspace": "/old/path"})
        )
        output.writestr("workspace/MEMORY.md", "legacy memory")

    target_data = tmp_path / "data"
    target_workspace = tmp_path / "workspace"
    result = restore_backup_archive(archive, target_data, target_workspace)

    assert (target_workspace / "MEMORY.md").read_text() == "legacy memory"
    assert result["agents"] == []
    restored = json.loads((target_data / "config.json").read_text())
    assert restored["agent_workspace"] == str(target_workspace.resolve())


def test_fresh_restore_ignores_archive_controlled_destinations(tmp_path, monkeypatch):
    source_data = tmp_path / "source-data"
    source_workspace = tmp_path / "source-workspace"
    outside_appdata = tmp_path / "outside-appdata"
    archive_workspace = tmp_path / "archive-controlled-workspace"
    _write_json(source_data / "config.json", {
        "agent_workspace": str(archive_workspace),
        "appdata_dir": str(outside_appdata),
    })
    source_workspace.mkdir()
    (source_workspace / "MEMORY.md").write_text("portable\n", encoding="utf-8")
    outside_appdata.mkdir()
    (outside_appdata / "user_datas.pkl").write_bytes(b"legacy")
    archive = tmp_path / "cow-backup.zip"
    create_backup_archive(archive, source_data, source_workspace)

    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    target_data = tmp_path / "target-data"
    result = restore_backup_archive(archive, target_data)

    assert result["workspace"] == str((fake_home / "cow").resolve())
    assert (fake_home / "cow" / "MEMORY.md").exists()
    assert not archive_workspace.exists()
    assert (target_data / "user_datas.pkl").read_bytes() == b"legacy"
    restored_config = json.loads((target_data / "config.json").read_text(encoding="utf-8"))
    assert restored_config["appdata_dir"] == ""


def test_multi_agent_backup_restore_preserves_all_isolated_workspaces(tmp_path):
    source_data = tmp_path / "source-data"
    primary = tmp_path / "source-primary"
    research = tmp_path / "source-research"
    _write_json(
        source_data / "config.json",
        {
            "agent_workspace": str(primary),
            "default_agent_id": "primary",
            "agents": [
                {
                    "id": "primary",
                    "name": "Primary",
                    "workspace": str(primary),
                    "enabled": True,
                },
                {
                    "id": "research",
                    "name": "Research",
                    "workspace": str(research),
                    "enabled": True,
                },
            ],
            "agent_bindings": [
                {"channel_type": "web", "agent_id": "research"}
            ],
        },
    )
    for workspace, marker in ((primary, "primary"), (research, "research")):
        (workspace / "memory" / "long-term").mkdir(parents=True)
        (workspace / "scheduler").mkdir()
        (workspace / "MEMORY.md").write_text(marker, encoding="utf-8")
        (workspace / "memory" / "long-term" / "index.db").write_bytes(
            marker.encode("utf-8")
        )
        (workspace / "scheduler" / "tasks.json").write_text(
            f'{{"owner":"{marker}"}}', encoding="utf-8"
        )

    archive = tmp_path / "multi.zip"
    summary = create_backup_archive(archive, source_data, primary)

    assert summary["layout"] == "agents"
    assert summary["contents"]["agent_workspaces"] == 2
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert "agents/primary/workspace/memory/long-term/index.db" in names
    assert "agents/research/workspace/memory/long-term/index.db" in names

    target_data = tmp_path / "target-data"
    target_root = tmp_path / "restored-agents"
    result = restore_backup_archive(archive, target_data, target_root)
    restored_config = json.loads(
        (target_data / "config.json").read_text(encoding="utf-8")
    )
    destinations = {
        item["id"]: Path(item["workspace"])
        for item in restored_config["agents"]
    }
    assert destinations == {
        "primary": (target_root / "primary").resolve(),
        "research": (target_root / "research").resolve(),
    }
    assert restored_config["agent_workspace"] == str(destinations["primary"])
    assert restored_config["agent_bindings"][0]["agent_id"] == "research"
    assert (destinations["primary"] / "MEMORY.md").read_text() == "primary"
    assert (destinations["research"] / "MEMORY.md").read_text() == "research"
    assert (destinations["primary"] / "memory/long-term/index.db").read_bytes() == b"primary"
    assert (destinations["research"] / "scheduler/tasks.json").exists()
    assert result["workspace_files"] == 6
    assert {item["id"] for item in result["agents"]} == {"primary", "research"}


def test_multi_agent_restore_reuses_matching_local_destinations(tmp_path):
    source_data = tmp_path / "source-data"
    source_primary = tmp_path / "source-primary"
    source_research = tmp_path / "source-research"
    config = {
        "default_agent_id": "primary",
        "agents": [
            {"id": "primary", "workspace": str(source_primary)},
            {"id": "research", "workspace": str(source_research)},
        ],
    }
    _write_json(source_data / "config.json", config)
    source_primary.mkdir()
    source_research.mkdir()
    (source_primary / "AGENT.md").write_text("new primary", encoding="utf-8")
    (source_research / "AGENT.md").write_text("new research", encoding="utf-8")
    archive = tmp_path / "multi.zip"
    create_backup_archive(archive, source_data, source_primary)

    target_data = tmp_path / "target-data"
    local_primary = tmp_path / "local-primary"
    local_research = tmp_path / "local-research"
    _write_json(
        target_data / "config.json",
        {
            "default_agent_id": "primary",
            "agents": [
                {"id": "primary", "workspace": str(local_primary)},
                {"id": "research", "workspace": str(local_research)},
            ],
        },
    )

    restore_backup_archive(archive, target_data)

    assert (local_primary / "AGENT.md").read_text() == "new primary"
    assert (local_research / "AGENT.md").read_text() == "new research"
    restored = json.loads((target_data / "config.json").read_text())
    assert {item["id"]: item["workspace"] for item in restored["agents"]} == {
        "primary": str(local_primary.resolve()),
        "research": str(local_research.resolve()),
    }


def test_multi_agent_restore_rejects_manifest_registry_mismatch(tmp_path):
    archive = tmp_path / "mismatch.zip"
    manifest = {
        "format": "cowagent-backup",
        "version": 2,
        "layout": "agents",
        "agents": [
            {
                "id": "research",
                "archive_root": "agents/research/workspace",
            }
        ],
    }
    config = {
        "default_agent_id": "primary",
        "agents": [{"id": "primary", "workspace": "/untrusted/path"}],
    }
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr("data/config.json", json.dumps(config))
        output.writestr("agents/research/workspace/MEMORY.md", "nope")

    with pytest.raises(ValueError, match="does not match"):
        restore_backup_archive(archive, tmp_path / "data", tmp_path / "agents")
