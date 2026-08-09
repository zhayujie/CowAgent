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


def test_omitted_default_falls_back_to_first_enabled_agent(tmp_path):
    registry = AgentRegistry.from_config(
        {
            "agents": [
                {"id": "writer", "workspace": str(tmp_path / "writer"), "enabled": False},
                {"id": "research", "workspace": str(tmp_path / "research")},
            ]
        }
    )

    assert registry.default_agent_id == "research"


def test_an_omitted_workspace_is_derived_from_the_instance_root(tmp_path):
    """Adding an Agent should cost a name, not a path. The default Agent keeps
    the instance root because that is where a single-Agent install already has
    everything: writing an `agents` list around an existing workspace must not
    relocate it."""
    root = tmp_path / "cow"
    registry = AgentRegistry.from_config(
        {
            "agent_workspace": str(root),
            "agents": [{"id": "main", "name": "Main"}, {"id": "sales", "name": "Sales"}],
        }
    )

    assert registry.get("main").workspace_path == root.resolve()
    assert registry.get("sales").workspace_path == (root / "agents" / "sales").resolve()


def test_the_explicit_default_is_the_one_that_keeps_the_instance_root(tmp_path):
    root = tmp_path / "cow"
    registry = AgentRegistry.from_config(
        {
            "agent_workspace": str(root),
            "default_agent_id": "sales",
            "agents": [{"id": "main"}, {"id": "sales"}],
        }
    )

    assert registry.get("sales").workspace_path == root.resolve()
    assert registry.get("main").workspace_path == (root / "agents" / "main").resolve()


def test_an_explicit_workspace_still_wins_and_an_empty_one_still_fails(tmp_path):
    registry = AgentRegistry.from_config(
        {
            "agent_workspace": str(tmp_path / "cow"),
            "agents": [{"id": "main"}, {"id": "sales", "workspace": str(tmp_path / "elsewhere")}],
        }
    )
    assert registry.get("sales").workspace_path == (tmp_path / "elsewhere").resolve()

    with pytest.raises(AgentRegistryError, match="non-empty string"):
        AgentRegistry.from_config(
            {"agent_workspace": str(tmp_path / "cow"), "agents": [{"id": "main", "workspace": ""}]}
        )


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
