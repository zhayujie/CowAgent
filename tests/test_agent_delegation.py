import threading
import time

from agent.protocol import get_cancel_registry
from agent.registry import AgentProfile, AgentRegistry
from agent.tools.agent_delegate.agent_delegate import (
    AgentDelegateTool,
    DelegationPolicy,
    attach_agent_delegate_to_tool,
)
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType


def _registry(disable_research=False):
    return AgentRegistry(
        [
            AgentProfile("primary", "Primary", "/tmp/delegate-primary"),
            AgentProfile(
                "research",
                "Research",
                "/tmp/delegate-research",
                enabled=not disable_research,
            ),
        ],
        "primary",
    )


def _context(agent_id="primary", session_id="user-session", **values):
    context = Context(ContextType.TEXT, "source turn", kwargs={})
    context["agent_id"] = agent_id
    context["session_id"] = session_id
    for key, value in values.items():
        context[key] = value
    return context


class FakeBridge:
    def __init__(self, registry=None):
        self.agent_registry = registry or _registry()
        self.calls = []

    @staticmethod
    def _cancel_key(agent_id, token, default_agent_id):
        return token if agent_id == default_agent_id else f"{agent_id}::{token}"

    def agent_reply(self, query, context=None, on_event=None):
        self.calls.append((query, context, on_event))
        return Reply(ReplyType.TEXT, "delegated result")


def _tool(bridge=None, config=None, context=None):
    tool = AgentDelegateTool(config=config)
    attach_agent_delegate_to_tool(
        tool,
        bridge or FakeBridge(),
        context or _context(),
    )
    return tool


def test_policy_defaults_to_other_agents_and_honors_allowlist():
    default = DelegationPolicy.from_config({})
    assert default.allows("primary", "research") is True
    assert default.allows("primary", "primary") is False

    restricted = DelegationPolicy.from_config(
        {"allowed_targets": {"primary": ["research"], "research": []}}
    )
    assert restricted.allows("primary", "research") is True
    assert restricted.allows("research", "primary") is False


def test_delegate_lists_only_enabled_allowed_targets():
    tool = _tool(config={"allowed_targets": {"primary": ["research"]}})

    result = tool.execute({"action": "list"})

    assert result.status == "success"
    assert result.result == {
        "source_agent_id": "primary",
        "agents": [{"id": "research", "name": "Research"}],
    }


def test_delegate_runs_target_with_source_attribution_and_private_relay_session():
    bridge = FakeBridge()
    tool = _tool(bridge=bridge)

    result = tool.execute({"agent_id": "research", "task": "Check the evidence"})

    assert result.status == "success"
    assert result.result["agent_id"] == "research"
    assert result.result["delegated_by"] == "primary"
    assert result.result["content"] == "delegated result"
    query, context, on_event = bridge.calls[0]
    assert "Delegated by Agent 'Primary' (primary)" in query
    assert context.get("agent_id") == "research"
    assert context.get("channel_type") == "agent"
    assert context.get("is_delegated_task") is True
    assert context.get("delegation_trace") == ["primary", "research"]
    assert context.get("session_id").startswith("delegate_primary_research_")
    assert on_event is None


def test_delegate_rejects_disabled_unknown_and_disallowed_targets():
    disabled = _tool(bridge=FakeBridge(_registry(disable_research=True)))
    result = disabled.execute({"agent_id": "research", "task": "Do work"})
    assert result.status == "error"
    assert "not available" in result.result

    missing = _tool()
    result = missing.execute({"agent_id": "missing", "task": "Do work"})
    assert result.status == "error"
    assert "not available" in result.result

    denied = _tool(config={"allowed_targets": {"primary": []}})
    result = denied.execute({"agent_id": "research", "task": "Do work"})
    assert result.status == "error"
    assert "not allowed" in result.result


def test_delegate_rejects_cycles_and_depth_overflow():
    cycle = _tool(
        context=_context(
            agent_id="research",
            delegation_trace=["primary", "research"],
            delegation_depth=1,
        )
    )
    result = cycle.execute({"agent_id": "primary", "task": "Send it back"})
    assert result.status == "error"
    assert "cycle rejected" in result.result

    too_deep = _tool(
        config={"max_depth": 1},
        context=_context(delegation_trace=["primary"], delegation_depth=1),
    )
    result = too_deep.execute({"agent_id": "research", "task": "Go deeper"})
    assert result.status == "error"
    assert "exceeds the maximum" in result.result


def test_delegate_enforces_message_limit():
    tool = _tool(config={"max_message_chars": 4})
    result = tool.execute({"agent_id": "research", "task": "12345"})
    assert result.status == "error"
    assert "exceeds 4 characters" in result.result


class BlockingBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def agent_reply(self, query, context=None, on_event=None):
        request_id = context.get("request_id")
        key = self._cancel_key(
            context.get("agent_id"),
            request_id,
            self.agent_registry.default_agent_id,
        )
        registry = get_cancel_registry()
        event = registry.register(key, session_id=context.get("session_id"))
        self.started.set()
        event.wait(0.5)
        if event.is_set():
            self.cancelled.set()
        registry.unregister(key)
        return Reply(ReplyType.TEXT, "late")


def test_delegate_timeout_cancels_target_run_without_blocking_caller():
    bridge = BlockingBridge()
    tool = _tool(bridge=bridge, config={"timeout_seconds": 0.05})
    started_at = time.monotonic()

    result = tool.execute({"agent_id": "research", "task": "Wait"})

    elapsed = time.monotonic() - started_at
    assert result.status == "error"
    assert "timed out" in result.result
    assert elapsed < 0.3
    assert bridge.started.is_set()
    assert bridge.cancelled.wait(0.3)
