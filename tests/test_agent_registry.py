from pathlib import Path

import pytest

from agent.registry import AgentProfile, AgentRegistry, AgentRegistryError


def test_legacy_config_synthesizes_default_agent(tmp_path):
    workspace = tmp_path / "cow"
    registry = AgentRegistry.from_config({"agent_workspace": str(workspace)})

    profile = registry.get()
    assert profile.id == "default"
    assert profile.name == "Default"
    assert profile.workspace_path == workspace.resolve()
    assert registry.default_agent_id == "default"


def test_configured_agents_keep_separate_workspaces(tmp_path):
    registry = AgentRegistry.from_config(
        {
            "default_agent_id": "writer",
            "agents": [
                {"id": "writer", "name": "Writer", "workspace": str(tmp_path / "writer")},
                {
                    "id": "research",
                    "name": "Research",
                    "workspace": str(tmp_path / "research"),
                    "model": "gpt-5",
                    "bot_type": "openai",
                },
            ],
        }
    )

    assert registry.get().id == "writer"
    assert registry.get("research").model == "gpt-5"
    assert registry.get("research").bot_type == "openai"
    assert [profile.id for profile in registry.list()] == ["research", "writer"]


@pytest.mark.parametrize("agent_id", ["", "has space", "/root", "x" * 65])
def test_invalid_agent_ids_are_rejected(tmp_path, agent_id):
    with pytest.raises(AgentRegistryError, match="agent id"):
        AgentRegistry.from_config(
            {"agents": [{"id": agent_id, "workspace": str(tmp_path / "one")}]}
        )


def test_duplicate_ids_and_workspaces_are_rejected(tmp_path):
    with pytest.raises(AgentRegistryError, match="duplicate agent id"):
        AgentRegistry.from_config(
            {
                "agents": [
                    {"id": "one", "workspace": str(tmp_path / "one")},
                    {"id": "one", "workspace": str(tmp_path / "two")},
                ],
                "default_agent_id": "one",
            }
        )

    with pytest.raises(AgentRegistryError, match="share workspace"):
        AgentRegistry.from_config(
            {
                "agents": [
                    {"id": "one", "workspace": str(tmp_path / "shared")},
                    {"id": "two", "workspace": str(tmp_path / "shared")},
                ],
                "default_agent_id": "one",
            }
        )


def test_default_agent_must_exist_and_be_enabled(tmp_path):
    with pytest.raises(AgentRegistryError, match="not configured"):
        AgentRegistry.from_config(
            {
                "agents": [{"id": "one", "workspace": str(tmp_path / "one")}],
                "default_agent_id": "missing",
            }
        )

    with pytest.raises(AgentRegistryError, match="disabled"):
        AgentRegistry.from_config(
            {
                "agents": [
                    {"id": "one", "workspace": str(tmp_path / "one"), "enabled": False}
                ],
                "default_agent_id": "one",
            }
        )


def test_registry_mutations_preserve_default_invariants(tmp_path):
    registry = AgentRegistry.from_config({"agent_workspace": str(tmp_path / "default")})
    second = AgentProfile(
        id="second",
        name="Second",
        workspace=str((tmp_path / "second").resolve()),
    )
    registry.upsert(second)

    registry.set_default("second")
    registry.set_enabled("default", False)
    assert registry.get().id == "second"
    assert registry.get_or_default("default").id == "second"

    with pytest.raises(AgentRegistryError, match="default agent cannot be disabled"):
        registry.set_enabled("second", False)
    with pytest.raises(AgentRegistryError, match="default agent cannot be removed"):
        registry.remove("second")

    removed = registry.remove("default")
    assert removed.id == "default"
    assert [profile.id for profile in registry.list()] == ["second"]


def test_profile_to_dict_omits_empty_overrides(tmp_path):
    profile = AgentProfile(
        id="default",
        name="Default",
        workspace=str(Path(tmp_path).resolve()),
    )
    assert profile.to_dict() == {
        "id": "default",
        "name": "Default",
        "workspace": str(Path(tmp_path).resolve()),
        "enabled": True,
    }
