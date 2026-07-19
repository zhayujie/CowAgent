import json
from pathlib import Path

from agent.registry import (
    AgentProfile,
    AgentRegistry,
    get_agent_registry,
    set_agent_registry,
)
from agent.tools.mcp.mcp_client import McpClientRegistry
from agent.tools.tool_manager import ToolManager


def test_tool_and_mcp_managers_are_keyed_by_agent_workspace(tmp_path):
    primary = tmp_path / "primary"
    research = tmp_path / "research"
    primary.mkdir()
    research.mkdir()
    (primary / "mcp.json").write_text(
        json.dumps({"mcpServers": {"primary-server": {"command": "one"}}}),
        encoding="utf-8",
    )
    (research / "mcp.json").write_text(
        json.dumps({"mcpServers": {"research-server": {"command": "two"}}}),
        encoding="utf-8",
    )

    primary_manager = ToolManager(str(primary))
    research_manager = ToolManager(str(research))

    assert primary_manager is ToolManager(str(primary))
    assert primary_manager is not research_manager
    assert primary_manager._mcp_json_path() == str(primary / "mcp.json")
    assert research_manager._mcp_json_path() == str(research / "mcp.json")
    assert primary_manager._load_mcp_configs()[0]["name"] == "primary-server"
    assert research_manager._load_mcp_configs()[0]["name"] == "research-server"
    primary_manager._mcp_status["primary-server"] = "ready"
    assert research_manager._mcp_status == {}

    assert ToolManager.shutdown_workspace(str(primary)) is True
    assert ToolManager.shutdown_workspace(str(research)) is True


def test_mcp_client_registries_do_not_share_server_names():
    primary = McpClientRegistry("test-primary")
    research = McpClientRegistry("test-research")

    class Marker:
        name = "filesystem"

        def shutdown(self):
            pass

    marker = Marker()
    with primary._registry_lock:
        primary._clients["filesystem"] = marker

    assert primary.get("filesystem") is marker
    assert research.get("filesystem") is None

    primary.shutdown_all()
    research.shutdown_all()


def test_builtin_skills_sync_to_every_enabled_agent_workspace(tmp_path):
    import app

    previous = get_agent_registry()
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
        ],
        "primary",
    )
    set_agent_registry(registry)
    try:
        app._sync_builtin_skills()
        project_skills = Path(app.__file__).parent / "skills"
        expected = {
            path.name
            for path in project_skills.iterdir()
            if (path / "SKILL.md").is_file()
        }
        assert expected
        for profile in registry.list():
            copied = {
                path.name for path in (profile.workspace_path / "skills").iterdir()
            }
            assert expected <= copied
    finally:
        set_agent_registry(previous)
