"""Deleting an Agent must not leave its project bindings behind.

``project_store`` is the sibling of ``session_prefs`` — same file shape, same
``{agent_id}::{session_id}`` key scheme, both documented that way. Deleting an
Agent sweeps the session-prefs store (its own overrides plus its id in other
conversations' rosters) but used to leave the project store untouched, so the
``{id}::*`` bindings of an Agent whose workspace had just been removed stayed in
``projects.json`` forever, and a later Agent created with the same id inherited
them.
"""

import json
from pathlib import Path

import pytest

from agent import team
from agent.admin import AgentAdminService
from agent.registry import AgentRegistry, set_agent_registry
from agent.workspace import project_store


def _pin(settings):
    set_agent_registry(AgentRegistry.from_config(team.resolve(settings)))


@pytest.fixture
def admin(tmp_path):
    primary = tmp_path / "primary"
    primary.mkdir()
    settings = {
        "agent_workspace": str(tmp_path),
        "default_agent_id": "primary",
        "agents": [
            {"id": "primary", "name": "Primary", "workspace": str(primary), "enabled": True}
        ],
        "channel_instances": [],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(settings), encoding="utf-8")
    _pin(settings)
    try:
        yield AgentAdminService(str(config_path)), tmp_path
    finally:
        set_agent_registry(None)


def _stored_sessions() -> dict:
    path = Path(project_store._store_file())
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("sessions") or {}


def _project(tmp_path, name: str) -> str:
    directory = tmp_path / name
    directory.mkdir()
    return str(directory)


def test_delete_agent_unbinds_its_project_bindings(admin, tmp_path):
    service, root = admin
    service.create_agent("research", "Research")

    research_project = _project(root, "alpha")
    primary_project = _project(root, "beta")
    project_store.set_project_dir("s1", research_project, agent_id="research")
    project_store.set_project_dir("s2", primary_project, agent_id="primary")
    assert project_store.get_project_dir("s1", agent_id="research") == project_store._normalize(
        research_project
    )

    service.delete_agent("research")

    # The gone Agent's binding is dropped …
    assert project_store.get_project_dir("s1", agent_id="research") is None
    assert not [key for key in _stored_sessions() if key.startswith("research::")]
    # … a surviving Agent's binding is untouched …
    assert project_store.get_project_dir("s2", agent_id="primary") == project_store._normalize(
        primary_project
    )
    # … and the directory itself survives: it is the user's folder, not the
    # Agent's, so deleting an Agent never removes a project from disk.
    assert Path(research_project).is_dir()


def test_recreated_agent_does_not_inherit_old_project_bindings(admin, tmp_path):
    """The id becomes reusable; the new Agent must start with no projects."""
    service, root = admin
    service.create_agent("research", "Research")
    project_store.set_project_dir("s1", _project(root, "alpha"), agent_id="research")
    assert any(key.startswith("research::") for key in _stored_sessions())

    service.delete_agent("research")
    service.create_agent("research", "Research again")

    assert project_store.get_project_dir("s1", agent_id="research") is None
    assert project_store.get_project_map("research") == {}


def test_forget_agent_of_an_unknown_id_changes_nothing(admin, tmp_path):
    service, root = admin
    project_store.set_project_dir("s1", _project(root, "alpha"), agent_id="primary")
    before = _stored_sessions()

    project_store.forget_agent("never-existed")

    assert _stored_sessions() == before
