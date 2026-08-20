import json
from pathlib import Path

import pytest

from agent.admin import (
    AgentAdminError,
    AgentAdminService,
    StaleAgentFileError,
)


@pytest.fixture
def admin(tmp_path):
    primary = tmp_path / "primary"
    primary.mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "default_agent_id": "primary",
                "agents": [
                    {
                        "id": "primary",
                        "name": "Primary",
                        "workspace": str(primary),
                        "enabled": True,
                    }
                ],
                "agent_bindings": [],
                "unrelated_setting": "preserved",
            }
        ),
        encoding="utf-8",
    )
    return AgentAdminService(str(config_path)), tmp_path, config_path


def test_create_agent_bootstraps_complete_workspace(admin):
    service, root, config_path = admin
    workspace = root / "research"

    created = service.create_agent("research", "Research", str(workspace))

    assert created["workspace"] == str(workspace.resolve())
    for filename in ("AGENT.md", "USER.md", "RULE.md", "MEMORY.md", "BOOTSTRAP.md"):
        assert (workspace / filename).is_file()
    for dirname in ("memory", "skills", "knowledge", "output", "scheduler"):
        assert (workspace / dirname).is_dir()
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["unrelated_setting"] == "preserved"
    assert [item["id"] for item in saved["agents"]] == ["primary", "research"]


def test_clone_agent_copies_workspace_and_registers_new_owner(admin):
    service, root, _ = admin
    source = root / "primary"
    (source / "AGENT.md").write_text("# Primary persona", encoding="utf-8")

    clone = root / "clone"
    service.create_agent("clone", "Clone", str(clone), clone_from="primary")

    assert (clone / "AGENT.md").read_text(encoding="utf-8") == "# Primary persona"
    primary = next(
        item for item in service.snapshot()["agents"] if item["id"] == "primary"
    )
    assert primary["workspace"] == str(source.resolve())


def test_archive_disables_profile_without_deleting_workspace(admin):
    service, root, _ = admin
    workspace = root / "research"
    service.create_agent("research", "Research", str(workspace))

    archived = service.archive_agent("research")

    assert archived["enabled"] is False
    assert workspace.is_dir()
    assert next(
        item for item in service.snapshot()["agents"] if item["id"] == "research"
    )["enabled"] is False


def test_default_agent_cannot_be_archived(admin):
    service, _, _ = admin
    with pytest.raises(Exception):
        service.archive_agent("primary")


def test_core_file_write_is_allowlisted_atomic_and_revision_guarded(admin):
    service, root, _ = admin
    workspace = root / "research"
    service.create_agent("research", "Research", str(workspace))
    original = service.read_core_file("research", "AGENT.md")

    saved = service.write_core_file(
        "research", "AGENT.md", "# Updated persona\n", original["revision"]
    )

    assert saved["revision"] != original["revision"]
    assert (workspace / "AGENT.md").read_text(encoding="utf-8") == "# Updated persona\n"
    with pytest.raises(StaleAgentFileError):
        service.write_core_file(
            "research", "AGENT.md", "stale", original["revision"]
        )
    with pytest.raises(AgentAdminError):
        service.read_core_file("research", "../config.json")


def test_duplicate_or_nonempty_workspace_is_rejected_without_config_change(admin):
    service, root, config_path = admin
    occupied = root / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")

    with pytest.raises(AgentAdminError):
        service.create_agent("research", "Research", str(occupied))

    assert config_path.read_text(encoding="utf-8") == before
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"
