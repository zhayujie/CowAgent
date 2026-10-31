"""The desktop shell relocates the Agent workspace through COW_DEFAULT_WORKSPACE;
everything that used to hardcode ~/cow must follow it while agent_workspace is
unset, or a moved install keeps reading the old place."""

import os
from pathlib import Path

from agent import team
from agent.registry import AgentRegistry
from common import cow_paths


def test_default_workspace_is_cow_in_home(monkeypatch, tmp_path):
    monkeypatch.delenv("COW_DEFAULT_WORKSPACE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path(cow_paths.default_workspace()) == tmp_path / "cow"


def test_blank_env_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("COW_DEFAULT_WORKSPACE", "  ")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path(cow_paths.default_workspace()) == tmp_path / "cow"


def test_default_workspace_follows_env_when_unset(monkeypatch, tmp_path):
    moved = tmp_path / "D" / "cow"
    monkeypatch.setenv("COW_DEFAULT_WORKSPACE", str(moved))

    registry = AgentRegistry.from_config({})
    assert Path(registry.get().workspace) == moved.resolve()
    assert team.instance_root({}) == moved


def test_explicit_agent_workspace_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COW_DEFAULT_WORKSPACE", str(tmp_path / "ignored"))
    explicit = tmp_path / "explicit"

    registry = AgentRegistry.from_config({"agent_workspace": str(explicit)})
    assert Path(registry.get().workspace) == explicit.resolve()
    assert os.path.basename(team.instance_root({"agent_workspace": str(explicit)})) == "explicit"
