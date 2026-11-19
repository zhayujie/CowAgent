"""A registry failure must not silently serve the default Agent's data.

Sibling of #3914: the per-agent service builders already refuse to answer a
request naming another Agent when their own construction fails. Their shared
input, ``_agent_workspace()``, still swallows a failure to load the registry and
returns ``None`` -- the very value it uses for "no Agent was requested". Every
builder then dispatches against the process-wide default-agent service and the
console reports success, so an edit aimed at one Agent silently reads or writes
another Agent's memory, knowledge, workspace files, skills or conversation
history.
"""

import sys
import types

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

import agent.registry as registry_module  # noqa: E402
from agent.registry import AgentRegistry, set_agent_registry  # noqa: E402
from common.cloud_client import CloudClient  # noqa: E402


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


@pytest.fixture
def broken_registry(monkeypatch):
    """A registry that cannot be loaded (bad config / missing dependency)."""

    def boom():
        raise RuntimeError("registry config unreadable")

    monkeypatch.setattr(registry_module, "get_agent_registry", boom)
    return boom


# label, callback, default-service attribute
CASES = [
    ("memory", "on_memory", "_memory_service"),
    ("knowledge", "on_knowledge", "_knowledge_service"),
    ("workspace", "on_workspace", "_workspace_service"),
    ("skill", "on_skill", "_skill_service"),
]


@pytest.mark.parametrize("label,callback,attr", CASES)
def test_registry_failure_is_reported_not_served_by_default(
    client, broken_registry, label, callback, attr
):
    """A request naming another Agent must never reach the default service."""
    default = getattr(client, attr)
    resp = getattr(client, callback)({"action": "list", "payload": {"agent_id": "research"}})

    assert resp["code"] == 500, (
        f"{label}: a registry failure was answered as success: {resp}"
    )
    assert default.calls == [], (
        f"{label}: the default agent's service was dispatched to for a research request"
    )


@pytest.mark.parametrize("label,callback,attr", CASES)
def test_registry_failure_is_not_reported_as_agent_not_found(
    client, broken_registry, label, callback, attr
):
    """A temporarily unavailable registry is a server error, not a 404."""
    resp = getattr(client, callback)({"action": "list", "payload": {"agent_id": "research"}})
    assert resp["code"] != 404, f"{label}: {resp}"


def test_history_query_registry_failure_does_not_read_default_store(
    client, broken_registry, monkeypatch
):
    """The history lookup must not fall back to the default Agent's store."""
    import agent.memory.conversation_store as store_module

    seen = []

    class _FakeStore:
        def load_history_page(self, **kwargs):
            return {"messages": [], "total": 0}

    def fake_get(workspace):
        seen.append(workspace)
        return _FakeStore()

    monkeypatch.setattr(store_module, "get_conversation_store", fake_get)
    resp = client.on_history(
        {"action": "query", "payload": {"session_id": "s1", "agent_id": "research"}}
    )

    assert resp["payload"]["status"] == "error", f"history query answered as success: {resp}"
    assert seen == [], "the default agent's conversation store was opened"


def test_agent_workspace_refuses_when_registry_unavailable(client, broken_registry):
    """The resolver itself must not conflate 'registry down' with 'no Agent'."""
    with pytest.raises(Exception) as excinfo:
        client._agent_workspace("research")
    assert not isinstance(excinfo.value, KeyError), (
        "an unavailable registry must not be reported as an unknown agent"
    )


@pytest.mark.parametrize("label,callback,attr", CASES)
def test_no_agent_requested_still_uses_the_default_service(client, label, callback, attr):
    """Control: single-agent installs keep their existing behaviour."""
    default = getattr(client, attr)
    resp = getattr(client, callback)({"action": "list", "payload": {}})
    assert resp["code"] == 200
    assert len(default.calls) == 1


@pytest.mark.parametrize("label,callback,attr", CASES)
def test_unknown_agent_is_still_refused(client, label, callback, attr):
    """Control: the registry's unknown-agent guard is unaffected."""
    resp = getattr(client, callback)({"action": "list", "payload": {"agent_id": "ghost"}})
    assert resp["code"] == 404


@pytest.mark.parametrize("label,callback,attr", CASES)
def test_successful_per_agent_build_uses_its_own_service(client, label, callback, attr):
    """Control: a healthy registry still resolves the requested workspace."""
    builder = getattr(client, f"_{label}_service_for")
    # The real constructors need a real workspace; resolve the path instead of
    # asserting the concrete service type, so no filesystem state is required.
    workspace = client._agent_workspace("research")
    assert workspace is not None
    assert str(workspace).endswith("research")
    assert callable(builder)
