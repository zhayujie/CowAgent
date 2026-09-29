"""Remote agent actions and skill requests address the agent they name.

A skill request naming an agent must operate on that agent's skills, and an
agent registration sent again for an agent that already exists must update it
rather than fail. Only the routing on the client is exercised here; the full
client needs its parent SDK, which is out of scope for a unit test.
"""

import sys
import types
from pathlib import Path

import pytest


if "linkai" not in sys.modules:
    _stub = types.ModuleType("linkai")

    class _LinkAIClient:
        def __init__(self, *a, **k):
            pass

    class _PushMsg:
        pass

    _stub.LinkAIClient = _LinkAIClient
    _stub.PushMsg = _PushMsg
    sys.modules["linkai"] = _stub

from common.cloud_client import CloudClient  # noqa: E402
from agent.registry import AgentRegistry, set_agent_registry  # noqa: E402


@pytest.fixture
def two_agents(tmp_path):
    primary = tmp_path / "primary"
    research = tmp_path / "agents" / "research"
    primary.mkdir()
    (research / "skills").mkdir(parents=True)
    settings = {
        "agent_workspace": str(tmp_path),
        "default_agent_id": "primary",
        "agents": [
            {"id": "primary", "name": "Primary", "workspace": str(primary), "enabled": True},
            {"id": "research", "name": "Research", "workspace": str(research), "enabled": True},
        ],
    }
    set_agent_registry(AgentRegistry.from_config(settings))
    try:
        yield research
    finally:
        set_agent_registry(None)


def _client():
    client = CloudClient.__new__(CloudClient)
    client._skill_service = object()
    return client


def test_skill_request_without_agent_keeps_the_shared_service(two_agents):
    client = _client()
    assert client._skill_service_for(None) is client._skill_service


def test_skill_request_naming_an_agent_uses_its_own_skills(two_agents):
    svc = _client()._skill_service_for("research")
    assert Path(svc.manager.custom_dir) == two_agents / "skills"


def test_skill_request_for_an_unknown_agent_is_refused(two_agents):
    resp = _client().on_skill({"action": "query", "payload": {"agent_id": "ghost"}})
    assert resp["code"] == 404


def test_registering_an_existing_agent_again_updates_it(two_agents, monkeypatch):
    client = _client()
    updates = []
    monkeypatch.setattr(client, "_handle_agent_update", lambda agent_id, data: updates.append((agent_id, data)))

    client._handle_agent_create("research", {"id": "research", "name": "Research 2", "model": "m1"})

    assert updates == [("research", {"id": "research", "name": "Research 2", "model": "m1"})]


def test_registering_the_default_alias_never_creates_an_agent(two_agents, monkeypatch):
    client = _client()
    updates = []
    monkeypatch.setattr(client, "_handle_agent_update", lambda agent_id, data: updates.append(agent_id))

    client._handle_agent_create("default", {"id": "default", "name": "Primary"})

    assert updates == ["default"]


def test_skill_request_for_the_default_alias_uses_the_default_agent(two_agents):
    svc = _client()._skill_service_for("default")
    assert Path(svc.manager.custom_dir) == two_agents.parent.parent / "primary" / "skills"


def test_registering_a_new_agent_does_not_take_the_update_path(two_agents, monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_handle_agent_update",
                        lambda *a: pytest.fail("a new agent must be created, not updated"))
    created = []

    class _Admin:
        def create_agent(self, **kwargs):
            created.append(kwargs["agent_id"])

    monkeypatch.setattr("agent.admin.get_agent_admin_service", lambda: _Admin())
    monkeypatch.setattr(CloudClient, "_reload_agents", staticmethod(lambda service, changed_agent_ids=None: None))

    client._handle_agent_create("writer", {"id": "writer", "name": "Writer"})

    assert created == ["writer"]


def test_changing_an_agents_model_drops_its_cached_runtime(two_agents, monkeypatch):
    client = _client()
    updated, reloaded = [], []

    class _Admin:
        def update_agent(self, agent_id, **fields):
            updated.append((agent_id, fields))

    monkeypatch.setattr("agent.admin.get_agent_admin_service", lambda: _Admin())
    monkeypatch.setattr(CloudClient, "_reload_agents",
                        staticmethod(lambda service, changed_agent_ids=None: reloaded.append(changed_agent_ids)))

    client._handle_agent_update("research", {"id": "research", "model": "m2"})

    assert updated == [("research", {"model": "m2"})]
    assert reloaded == [["research"]]
