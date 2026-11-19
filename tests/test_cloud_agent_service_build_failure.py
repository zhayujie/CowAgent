"""A failed per-agent service build must not silently serve the default agent.

Cloud console callbacks carry an ``agent_id``. When the per-agent service
cannot be built (missing dependency, unreadable index, bad config), the client
must report the failure instead of dispatching the action against the
process-wide default-agent service -- otherwise an edit aimed at one Agent
silently reads or writes another Agent's memory, knowledge or workspace files.
"""

import importlib
import sys
import types
from unittest.mock import Mock

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
    research.mkdir(parents=True)
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
        yield
    finally:
        set_agent_registry(None)


class _DefaultService:
    """Stand-in for the process-wide default-agent service."""

    def __init__(self, name):
        self.name = name
        self.calls = []

    def dispatch(self, action, payload):
        self.calls.append((action, payload))
        return {"action": action, "code": 200, "payload": {"owner": "default"}}


@pytest.fixture
def client(two_agents):
    c = CloudClient.__new__(CloudClient)
    c._memory_service = _DefaultService("memory")
    c._knowledge_service = _DefaultService("knowledge")
    c._workspace_service = _DefaultService("workspace")
    c._skill_service = _DefaultService("skill")
    return c


# label, callback, default-service attribute, module, class
CASES = [
    ("memory", "on_memory", "_memory_service", "agent.memory.service", "MemoryService"),
    ("knowledge", "on_knowledge", "_knowledge_service", "agent.knowledge.service", "KnowledgeService"),
    ("workspace", "on_workspace", "_workspace_service", "agent.workspace.service", "WorkspaceService"),
]


@pytest.mark.parametrize("label,callback,attr,mod_name,cls_name", CASES)
def test_failed_per_agent_build_is_reported_not_served_by_default(
    client, label, callback, attr, mod_name, cls_name, monkeypatch
):
    """The default agent's store must never answer a request naming another agent."""
    default = getattr(client, attr)
    module = importlib.import_module(mod_name)
    monkeypatch.setattr(
        module, cls_name, Mock(side_effect=RuntimeError("index corrupt"))
    )

    resp = getattr(client, callback)({"action": "list", "payload": {"agent_id": "research"}})

    assert resp["code"] == 500, (
        f"{label}: a failed per-agent build was answered as success: {resp}"
    )
    assert default.calls == [], (
        f"{label}: the default agent's service was dispatched to for a research request"
    )


@pytest.mark.parametrize("label,callback,attr,mod_name,cls_name", CASES)
def test_no_agent_requested_still_uses_the_default_service(
    client, label, callback, attr, mod_name, cls_name
):
    """Control: single-agent installs keep their existing behaviour."""
    default = getattr(client, attr)
    resp = getattr(client, callback)({"action": "list", "payload": {}})
    assert resp["code"] == 200
    assert len(default.calls) == 1


@pytest.mark.parametrize("label,callback,attr,mod_name,cls_name", CASES)
def test_successful_per_agent_build_uses_its_own_service(
    client, label, callback, attr, mod_name, cls_name, monkeypatch
):
    """Control: a healthy per-agent build still wins over the default service."""
    module = importlib.import_module(mod_name)
    sentinel = object()
    monkeypatch.setattr(module, cls_name, Mock(return_value=sentinel))
    assert getattr(client, f"_{label}_service_for")("research") is sentinel


@pytest.mark.parametrize("label,callback,attr,mod_name,cls_name", CASES)
def test_unknown_agent_is_still_refused(
    client, label, callback, attr, mod_name, cls_name
):
    """Control: the registry's unknown-agent guard is unaffected."""
    resp = getattr(client, callback)({"action": "list", "payload": {"agent_id": "ghost"}})
    assert resp["code"] == 404


def test_skill_service_build_failure_already_returns_none(client, monkeypatch):
    """The sibling callback is the shape the other three should follow."""
    module = importlib.import_module("agent.skills.service")
    monkeypatch.setattr(
        module, "SkillService", Mock(side_effect=RuntimeError("broken"))
    )
    assert client._skill_service_for("research") is None
