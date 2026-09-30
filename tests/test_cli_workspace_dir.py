"""The CLI resolves an Agent's workspace from the roster file, not config.json alone."""

import json

import pytest

from agent.admin import AgentAdminService
from agent.registry import set_agent_registry
from cli import utils as cli_utils


@pytest.fixture
def install(tmp_path, monkeypatch):
    root = tmp_path / "cow"
    root.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    config = data / "config.json"
    config.write_text(json.dumps({"agent_workspace": str(root)}), encoding="utf-8")
    monkeypatch.setenv("COW_DATA_DIR", str(data))
    set_agent_registry(None)
    try:
        yield AgentAdminService(str(config)), root, config
    finally:
        set_agent_registry(None)


def test_config_json_is_read_from_the_data_dir(install):
    _, root, _ = install
    assert cli_utils.load_config_json() == {"agent_workspace": str(root)}


def test_an_agent_that_only_exists_in_team_json_resolves(install):
    service, root, config = install
    service.create_agent("agent-abc123", "Researcher")

    assert "agents" not in json.loads(config.read_text(encoding="utf-8"))
    expected = (root / "agents" / "agent-abc123").resolve()
    assert cli_utils.get_workspace_dir("agent-abc123") == str(expected)


def test_the_default_agent_still_resolves_to_the_instance_root(install):
    service, root, _ = install
    service.create_agent("agent-abc123", "Researcher")

    assert cli_utils.get_workspace_dir() == str(root.resolve())


def test_an_unknown_agent_still_raises(install):
    with pytest.raises(KeyError):
        cli_utils.get_workspace_dir("missing")
