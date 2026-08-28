"""Tests for delegation as an addressable run rather than a blocking call.

The contributor's original suite (tests/test_agent_delegation.py) still covers
the guards. This one covers what changed: the handle, the parent link across
the worker thread, and collecting a result after the fact.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.conversation_store import ConversationStore
from agent.registry import AgentProfile, AgentRegistry
from agent.tools.agent_delegate.agent_delegate import (
    TASK_SOURCE,
    AgentDelegateTool,
    attach_agent_delegate_to_tool,
)
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.utils import clear_agent_run_id, set_agent_run_id


def _registry():
    return AgentRegistry(
        [
            AgentProfile("primary", "Primary", "/tmp/delegate-primary"),
            AgentProfile("research", "Research", "/tmp/delegate-research"),
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


class RecordingBridge:
    """A bridge whose target turn we can hold open, backed by a real store.

    ``agent_reply`` opens the run the way AgentBridge does -- honouring the
    caller-assigned id and parent -- so the rows under test are the real ones.
    """

    def __init__(self, store, gate: threading.Event = None):
        self.agent_registry = _registry()
        self._store = store
        self._gate = gate
        self.contexts = []
        self.started = threading.Event()
        self.reply = Reply(ReplyType.TEXT, "delegated result")
        self.raise_on_call = None

    @staticmethod
    def _cancel_key(agent_id, token, default_agent_id):
        return token if agent_id == default_agent_id else f"{agent_id}::{token}"

    def get_conversation_store(self, agent_id=None):
        return self._store

    def agent_reply(self, query, context=None, on_event=None):
        self.contexts.append(context)
        self._store.create_run(
            context.get("run_id"),
            agent_id=context.get("agent_id"),
            session_id=context.get("session_id"),
            parent_run_id=context.get("parent_run_id") or "",
            task_source=context.get("task_source") or "",
        )
        self.started.set()
        if self._gate is not None:
            self._gate.wait(2)
        if self.raise_on_call:
            self._store.finish_run(context.get("run_id"), status="failed")
            raise RuntimeError(self.raise_on_call)
        self._store.finish_run(context.get("run_id"), status="done")
        return self.reply


class DelegationHandleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self._tmp.name) / "index.db")
        self.gate = threading.Event()

    def tearDown(self):
        self.gate.set()
        self._tmp.cleanup()

    def _tool(self, bridge, config=None, context=None):
        tool = AgentDelegateTool(config=config)
        attach_agent_delegate_to_tool(tool, bridge, context or _context())
        return tool

    def test_delegation_returns_a_handle_instead_of_blocking(self):
        bridge = RecordingBridge(self.store, self.gate)
        tool = self._tool(bridge)
        started_at = time.monotonic()

        result = tool.execute(
            {"agent_id": "research", "task": "Dig into it", "wait_seconds": 0}
        )

        self.assertLess(time.monotonic() - started_at, 0.5)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["status"], "running")
        self.assertTrue(result.result["run_id"])
        self.assertNotIn("content", result.result)

    def test_the_target_run_is_a_child_of_the_delegating_run(self):
        """The worker runs on another thread, where the ambient id is gone, so
        this is the case a context variable alone cannot carry.
        """
        bridge = RecordingBridge(self.store)
        tool = self._tool(bridge)
        token = set_agent_run_id("caller-run")
        try:
            result = tool.execute({"agent_id": "research", "task": "Dig into it"})
        finally:
            clear_agent_run_id(token)

        self.assertEqual(result.status, "success")
        handle = result.result["run_id"]
        row = self.store.get_run(handle)
        self.assertEqual(row["parent_run_id"], "caller-run")
        self.assertEqual(row["agent_id"], "research")
        self.assertEqual(row["task_source"], TASK_SOURCE)
        self.assertEqual(
            [c["run_id"] for c in self.store.list_runs(parent_run_id="caller-run")],
            [handle],
        )

    def test_waiting_long_enough_still_returns_the_result_inline(self):
        bridge = RecordingBridge(self.store)
        tool = self._tool(bridge)

        result = tool.execute({"agent_id": "research", "task": "Dig into it"})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["status"], "done")
        self.assertEqual(result.result["content"], "delegated result")

    def test_a_handle_can_be_collected_after_the_fact(self):
        bridge = RecordingBridge(self.store, self.gate)
        tool = self._tool(bridge)
        handle = tool.execute(
            {"agent_id": "research", "task": "Dig into it", "wait_seconds": 0}
        ).result["run_id"]

        pending = tool.execute({"action": "check", "run_id": handle})
        self.assertEqual(pending.status, "success")
        self.assertEqual(pending.result["status"], "running")
        self.assertNotIn("content", pending.result)

        self.gate.set()
        self.assertTrue(self._settled(tool, handle))

        done = tool.execute({"action": "check", "run_id": handle})
        self.assertEqual(done.status, "success")
        self.assertEqual(done.result["status"], "done")
        self.assertEqual(done.result["content"], "delegated result")

    def test_the_result_survives_the_process_that_started_it(self):
        """Only the run row is durable, so check has to work with the tracker
        entry gone -- otherwise a restart loses finished work.
        """
        bridge = RecordingBridge(self.store)
        tool = self._tool(bridge)
        handle = tool.execute({"agent_id": "research", "task": "Dig into it"}).result[
            "run_id"
        ]

        import agent.tools.agent_delegate.agent_delegate as module

        module._tracker = module._DelegationTracker()

        recovered = tool.execute({"action": "check", "run_id": handle})
        self.assertEqual(recovered.status, "success")
        self.assertEqual(recovered.result["status"], "done")
        self.assertEqual(recovered.result["content"], "delegated result")

    def test_check_rejects_unknown_and_foreign_handles(self):
        bridge = RecordingBridge(self.store)
        tool = self._tool(bridge)
        handle = tool.execute({"agent_id": "research", "task": "Dig into it"}).result[
            "run_id"
        ]

        unknown = tool.execute({"action": "check", "run_id": "nope"})
        self.assertEqual(unknown.status, "error")
        self.assertIn("Unknown delegation handle", unknown.result)

        # The same handle read by the other Agent must not resolve.
        other = self._tool(bridge, context=_context(agent_id="research"))
        foreign = other.execute({"action": "check", "run_id": handle})
        self.assertEqual(foreign.status, "error")
        self.assertIn("Unknown delegation handle", foreign.result)

    def test_check_refuses_runs_that_are_not_delegations(self):
        bridge = RecordingBridge(self.store)
        tool = self._tool(bridge)
        self.store.create_run("plain-run", agent_id="research", session_id="s1")

        result = tool.execute({"action": "check", "run_id": "plain-run"})

        self.assertEqual(result.status, "error")
        self.assertIn("not a delegation", result.result)

    def test_a_failed_target_is_reported_through_the_handle(self):
        bridge = RecordingBridge(self.store, self.gate)
        bridge.raise_on_call = "target exploded"
        tool = self._tool(bridge)
        handle = tool.execute(
            {"agent_id": "research", "task": "Dig into it", "wait_seconds": 0}
        ).result["run_id"]

        self.gate.set()
        self.assertTrue(self._settled(tool, handle))

        result = tool.execute({"action": "check", "run_id": handle})
        self.assertEqual(result.status, "error")
        self.assertIn("target exploded", result.result)

    def test_cancel_stops_a_running_delegation(self):
        bridge = RecordingBridge(self.store, self.gate)
        tool = self._tool(bridge)
        handle = tool.execute(
            {"agent_id": "research", "task": "Dig into it", "wait_seconds": 0}
        ).result["run_id"]
        self.assertTrue(bridge.started.wait(1))

        cancelled = tool.execute({"action": "cancel", "run_id": handle})

        self.assertEqual(cancelled.status, "success")
        self.assertTrue(cancelled.result["cancelled"])
        self.assertEqual(cancelled.result["status"], "cancelled")

    def test_cancel_rejects_foreign_handles(self):
        bridge = RecordingBridge(self.store, self.gate)
        tool = self._tool(bridge)
        handle = tool.execute(
            {"agent_id": "research", "task": "Dig into it", "wait_seconds": 0}
        ).result["run_id"]

        other = self._tool(bridge, context=_context(agent_id="research"))
        result = other.execute({"action": "cancel", "run_id": handle})

        self.assertEqual(result.status, "error")
        self.assertIn("Unknown delegation handle", result.result)

    def test_a_late_answer_is_still_attached_to_the_run(self):
        """A target that overruns its budget gets cancelled, but if it answers
        anyway the work should not be thrown away.
        """
        bridge = RecordingBridge(self.store, self.gate)
        tool = self._tool(bridge, config={"timeout_seconds": 0.05})

        timed_out = tool.execute({"agent_id": "research", "task": "Dig into it"})
        self.assertEqual(timed_out.status, "error")
        self.assertIn("timed out", timed_out.result)

        handle = self.store.list_runs(task_source=TASK_SOURCE)[0]["run_id"]
        self.gate.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            extras = self.store.get_run(handle).get("extras") or {}
            if "result" in extras:
                break
            time.sleep(0.01)
        self.assertEqual(
            (self.store.get_run(handle).get("extras") or {}).get("result"),
            "delegated result",
        )

    def test_the_tracker_keeps_live_work_when_it_trims(self):
        import agent.tools.agent_delegate.agent_delegate as module

        tracker = module._DelegationTracker(limit=2)
        live = module._Delegation(
            "live", "primary", "research", "Research", "s", "r", 1, 60.0
        )
        tracker.add(live)
        for index in range(5):
            finished = module._Delegation(
                f"old-{index}", "primary", "research", "Research", "s", "r", 1, 60.0
            )
            finished.settle("done", content="x")
            tracker.add(finished)

        self.assertIsNotNone(tracker.get("live"))
        self.assertIsNotNone(tracker.get("old-4"))
        self.assertIsNone(tracker.get("old-0"))

    @staticmethod
    def _settled(tool, handle, timeout=2.0):
        import agent.tools.agent_delegate.agent_delegate as module

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            entry = module._tracker.get(handle)
            if entry is not None and entry.status != "running":
                return True
            time.sleep(0.01)
        return False


if __name__ == "__main__":
    unittest.main()
