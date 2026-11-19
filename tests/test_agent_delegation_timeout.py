import threading
import time
from pathlib import Path

from agent.protocol import Agent, LLMModel, get_cancel_registry
from agent.registry import AgentProfile, AgentRegistry
from agent.routing import AgentRouter
from agent.tools.agent_delegate.agent_delegate import (
    AgentDelegateTool,
    _local_run_deadline,
    attach_agent_delegate_to_tool,
)
from bridge.agent_bridge import AgentBridge
from bridge.context import Context, ContextType


class OwnedBackend(LLMModel):
    def __init__(self, fast=False):
        super().__init__("owned-local-fixture")
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        if fast:
            self.release.set()

    def call_stream(self, request):
        self.started.set()
        try:
            while not self.release.wait(0.005):
                yield {"choices": [{"delta": {"content": "fixture "}}]}
            yield {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}
        finally:
            self.closed.set()


def make_tool(tmp_path, monkeypatch, fast=False):
    # Real bridge, Agent, executor and cancel registry; only the LLM backend is
    # an owned local fixture, so no provider or network call is made.
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
        ],
        "primary",
    )
    for profile in registry.list():
        Path(profile.workspace).mkdir()
    backend = OwnedBackend(fast)
    agent = Agent(
        "Return the local fixture",
        model=backend,
        tools=[],
        enable_skills=False,
        workspace_dir=str(tmp_path / "research"),
        max_steps=1,
        output_mode="logger",
    )
    bridge = AgentBridge.__new__(AgentBridge)
    bridge.agent_registry = registry
    bridge.agent_router = AgentRouter(registry)
    bridge._agent_instances = {}
    bridge._agents_lock = threading.RLock()
    monkeypatch.setattr(bridge, "get_agent", lambda **kwargs: agent)
    monkeypatch.setattr(bridge, "_schedule_mcp_hot_reload", lambda *args: None)
    context = Context(
        ContextType.TEXT,
        "source",
        kwargs={
            "agent_id": "primary",
            "session_id": "owned-timeout",
            "is_delegated_task": True,
            "delegation_members": ["research"],
        },
    )
    tool = AgentDelegateTool({"timeout_seconds": 5})
    attach_agent_delegate_to_tool(tool, bridge, context)
    # Warm SQLite and imports with a healthy run so the short deadlines below
    # exercise in-flight work rather than cold imports.
    backend.release.set()
    warm = AgentDelegateTool({"timeout_seconds": 5})
    attach_agent_delegate_to_tool(warm, bridge, context)
    assert warm.execute({"agent_id": "research", "task": "Warm owned fixture"}).status == "success"
    backend.started.clear()
    backend.closed.clear()
    if not fast:
        backend.release.clear()
    return tool, backend


def run_with_rescue(backend, seconds, call):
    # Releases the backend if the code under test fails to cancel it, so a
    # regression fails instead of hanging.
    rescue = threading.Timer(seconds, backend.release.set)
    rescue.start()
    try:
        return call()
    finally:
        rescue.cancel()
        rescue.join()


def test_local_run_honors_budget(tmp_path, monkeypatch):
    tool, backend = make_tool(tmp_path, monkeypatch)
    tool.config["timeout_seconds"] = 2
    result = run_with_rescue(
        backend, 5, lambda: tool.execute({"agent_id": "research", "task": "Wait for local fixture"})
    )
    assert result.status == "error", result
    assert "time budget" in result.result
    assert backend.started.is_set()
    assert backend.closed.is_set()


def test_fast_local_delegation_still_completes(tmp_path, monkeypatch):
    tool, backend = make_tool(tmp_path, monkeypatch, fast=True)
    result = tool.execute({"agent_id": "research", "task": "Return local fixture"})
    assert result.status == "success", result
    assert backend.closed.is_set()
    assert "done" in result.result["content"]


def test_deadline_during_bridge_initialization_reaches_real_executor(tmp_path, monkeypatch):
    tool, backend = make_tool(tmp_path, monkeypatch)
    tool.config["timeout_seconds"] = 0.05
    original = tool.agent_bridge.route_context

    def delayed(context):
        # AgentBridge registers its token only after routing. The timer must
        # still reach the actual executor when that registration comes late.
        time.sleep(0.1)
        return original(context)

    monkeypatch.setattr(tool.agent_bridge, "route_context", delayed)
    result = run_with_rescue(
        backend, 5, lambda: tool.execute({"agent_id": "research", "task": "Start after the budget"})
    )
    assert result.status == "error"
    assert "time budget" in result.result
    assert not backend.started.is_set()


def test_timed_out_run_keeps_session_lock_through_cleanup(tmp_path, monkeypatch):
    tool, backend = make_tool(tmp_path, monkeypatch)
    tool.config["timeout_seconds"] = 2
    cleanup_entered = threading.Event()
    cleanup_release = threading.Event()
    calls = []
    original = backend.call_stream

    def gated(request):
        calls.append("start")
        try:
            yield from original(request)
        finally:
            if len(calls) == 1:
                cleanup_entered.set()
                cleanup_release.wait(5)
            calls.append("close")

    monkeypatch.setattr(backend, "call_stream", gated)
    first = []
    second = []
    worker = threading.Thread(
        target=lambda: first.append(tool.execute({"agent_id": "research", "task": "First"}))
    )
    second_tool = AgentDelegateTool({"timeout_seconds": 5})
    attach_agent_delegate_to_tool(second_tool, tool.agent_bridge, tool.current_context)
    follower = threading.Thread(
        target=lambda: second.append(second_tool.execute({"agent_id": "research", "task": "Second"}))
    )
    # Releases both gates if the first run is never cancelled, so a regression
    # fails the assertions below instead of hanging.
    rescue = threading.Timer(6, lambda: (backend.release.set(), cleanup_release.set()))
    rescue.start()
    worker.start()
    try:
        assert cleanup_entered.wait(10)
        follower.start()
        time.sleep(0.08)
        assert calls == ["start"]
        assert worker.is_alive() and follower.is_alive()
        backend.release.set()
        cleanup_release.set()
        worker.join(3)
        follower.join(3)
        assert not worker.is_alive() and not follower.is_alive()
        assert first[0].status == "error"
        assert second[0].status == "success", second
        assert "done" in second[0].result["content"]
        assert calls == ["start", "close", "start", "close"]
    finally:
        rescue.cancel()
        rescue.join()
        backend.release.set()
        cleanup_release.set()
        worker.join(3)
        if follower.ident is not None:
            follower.join(3)


def test_deadline_never_cancels_or_unregisters_a_replacement_registry_entry(tmp_path, monkeypatch):
    tool, backend = make_tool(tmp_path, monkeypatch, fast=True)
    registry = get_cancel_registry()
    key = "research::owned-replacement-case"
    try:
        with _local_run_deadline(
            tool.agent_bridge, "research", "owned-replacement-case", "owned-session", 0.02
        ) as expired:
            original = registry.get_event(key)
            registry.unregister(key)
            replacement = registry.register(key)
            assert expired.wait(1)
            assert original.is_set()
            assert not replacement.is_set()
        assert registry.get_event(key) is replacement
        assert not replacement.is_set()
    finally:
        registry.unregister(key)


def test_completed_deadline_cannot_cancel_a_followup_entry(tmp_path, monkeypatch):
    tool, backend = make_tool(tmp_path, monkeypatch, fast=True)
    registry = get_cancel_registry()
    key = "research::owned-completed-case"
    with _local_run_deadline(
        tool.agent_bridge, "research", "owned-completed-case", "owned-session", 0.02
    ):
        pass
    assert registry.get_event(key) is None
    replacement = registry.register(key)
    try:
        time.sleep(0.05)
        assert registry.get_event(key) is replacement
        assert not replacement.is_set()
    finally:
        registry.unregister(key)
