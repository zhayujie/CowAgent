import threading
from types import SimpleNamespace

from agent.registry import AgentRegistry
from bridge.agent_bridge import AgentBridge


class _FakeInitializer:
    def __init__(self, registry):
        self.registry = registry
        self.calls = []

    def initialize_agent(self, session_id=None, agent_id=None):
        profile = self.registry.get(agent_id)
        self.calls.append((profile.id, session_id))
        return SimpleNamespace(
            agent_id=profile.id,
            workspace_dir=profile.workspace,
            messages=[],
            messages_lock=threading.RLock(),
        )


def _bridge(tmp_path):
    registry = AgentRegistry.from_config(
        {
            "default_agent_id": "primary",
            "agents": [
                {
                    "id": "primary",
                    "name": "Primary",
                    "workspace": str(tmp_path / "primary"),
                },
                {
                    "id": "research",
                    "name": "Research",
                    "workspace": str(tmp_path / "research"),
                },
            ],
        }
    )
    bridge = object.__new__(AgentBridge)
    bridge.agent_registry = registry
    bridge._agent_instances = {}
    bridge._default_agents = {}
    bridge._agents_lock = threading.RLock()
    bridge.agents = {}
    bridge.default_agent = None
    bridge.initializer = _FakeInitializer(registry)
    return bridge


def test_same_session_id_isolated_by_agent(tmp_path):
    bridge = _bridge(tmp_path)

    primary = bridge.get_agent(session_id="shared")
    research = bridge.get_agent(session_id="shared", agent_id="research")

    assert primary is not research
    assert primary.workspace_dir != research.workspace_dir
    assert bridge.get_agent(session_id="shared") is primary
    assert bridge.get_agent(session_id="shared", agent_id="research") is research
    assert bridge.initializer.calls == [
        ("primary", "shared"),
        ("research", "shared"),
    ]


def test_legacy_agents_view_contains_only_default_profile(tmp_path):
    bridge = _bridge(tmp_path)

    primary = bridge.get_agent(session_id="one")
    bridge.get_agent(session_id="two", agent_id="research")

    assert bridge.agents == {"one": primary}
    assert set(bridge._agent_instances) == {
        ("primary", "one"),
        ("research", "two"),
    }


def test_default_runtime_is_per_agent_workspace(tmp_path):
    bridge = _bridge(tmp_path)

    primary = bridge.get_agent()
    research = bridge.get_agent(agent_id="research")

    assert primary is bridge.default_agent
    assert primary is not research
    assert bridge.get_agent() is primary
    assert bridge.get_agent(agent_id="research") is research


def test_clear_session_and_agent_do_not_evict_other_agents(tmp_path):
    bridge = _bridge(tmp_path)
    primary = bridge.get_agent(session_id="shared")
    research = bridge.get_agent(session_id="shared", agent_id="research")
    bridge.get_agent(session_id="other", agent_id="research")

    bridge.clear_session("shared", agent_id="research")
    assert bridge.get_cached_agent("shared", agent_id="research") is None
    assert bridge.get_cached_agent("shared") is primary

    assert bridge.clear_agent("research") == 1
    assert bridge.get_cached_agent("shared") is primary
    assert bridge.get_cached_agent("other", agent_id="research") is None
    assert research not in [item[2] for item in bridge.iter_agent_instances()]


def test_iter_agent_instances_reports_agent_and_session(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.get_agent()
    bridge.get_agent(agent_id="research")
    bridge.get_agent(session_id="chat")
    bridge.get_agent(session_id="chat", agent_id="research")

    keys = {
        (agent_id, session_id)
        for agent_id, session_id, _agent in bridge.iter_agent_instances()
    }
    assert keys == {
        ("primary", None),
        ("research", None),
        ("primary", "chat"),
        ("research", "chat"),
    }


def test_non_default_cancel_keys_are_namespaced(tmp_path):
    bridge = _bridge(tmp_path)
    assert bridge._cancel_key("primary", "session", "primary") == "session"
    assert bridge._cancel_key("research", "session", "primary") == "research::session"
