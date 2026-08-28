"""Tests for opening and closing a run around a turn.

Exercised through AgentBridge._begin_run / _end_run against a real store, so
these cover the actual rows written rather than a mocked call log.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.conversation_store import ConversationStore
from bridge.agent_bridge import AgentBridge
from common.runtime_identity import identity_scope
from common.utils import current_agent_run_id


class _Bridge:
    """The two methods under test, bound to a store we control.

    Built without AgentBridge.__init__ (which boots a whole runtime) so the
    test exercises the real methods against a temporary database.
    """

    def __init__(self, store):
        self._store = store

    _begin_run = AgentBridge._begin_run
    _end_run = AgentBridge._end_run

    def get_conversation_store(self, agent_id=None):
        return self._store


def _context(**kwargs):
    """A stand-in for bridge.Context: only .get is used by the code path."""
    return SimpleNamespace(get=lambda key, default=None: kwargs.get(key, default))


class RunLifecycleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self._tmp.name) / "index.db")
        self.bridge = _Bridge(self.store)

    def tearDown(self):
        self._tmp.cleanup()

    def test_run_is_recorded_and_becomes_the_ambient_id(self):
        run_id, token, store = self.bridge._begin_run("s1", "sales", None)

        self.assertIsNotNone(run_id)
        self.assertEqual(current_agent_run_id(), run_id)
        run = self.store.get_run(run_id)
        self.assertEqual(run["agent_id"], "sales")
        self.assertEqual(run["session_id"], "s1")
        self.assertEqual(run["status"], "running")
        self.assertIsNone(run["ended_at"])

        self.bridge._end_run(store, run_id, token, "done")

        run = self.store.get_run(run_id)
        self.assertEqual(run["status"], "done")
        self.assertIsNotNone(run["ended_at"])
        # The ambient id must not survive the turn.
        self.assertIsNone(current_agent_run_id())

    def test_failure_is_recorded_with_its_message(self):
        run_id, token, store = self.bridge._begin_run("s1", "sales", None)
        self.bridge._end_run(store, run_id, token, "failed", "boom")

        run = self.store.get_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error"], "boom")

    def test_cancelled_is_distinct_from_failed(self):
        run_id, token, store = self.bridge._begin_run("s1", "sales", None)
        self.bridge._end_run(store, run_id, token, "cancelled")

        self.assertEqual(self.store.get_run(run_id)["status"], "cancelled")

    def test_a_run_started_inside_another_records_its_parent(self):
        """A delegation or spawn nests: the tree has to stay walkable."""
        outer_id, outer_token, outer_store = self.bridge._begin_run("s1", "sales", None)
        inner_id, inner_token, inner_store = self.bridge._begin_run("s1", "support", None)

        self.assertEqual(self.store.get_run(inner_id)["parent_run_id"], outer_id)
        self.assertEqual(self.store.get_run(outer_id)["parent_run_id"], "")
        children = self.store.list_runs(parent_run_id=outer_id)
        self.assertEqual([c["run_id"] for c in children], [inner_id])

        self.bridge._end_run(inner_store, inner_id, inner_token, "done")
        # Closing the inner run restores the outer one as ambient.
        self.assertEqual(current_agent_run_id(), outer_id)
        self.bridge._end_run(outer_store, outer_id, outer_token, "done")
        self.assertIsNone(current_agent_run_id())

    def test_caller_may_name_the_run_before_the_work_starts(self):
        """A handle has to exist before the turn does, or it cannot be handed
        back to a caller that is not going to wait for the answer.
        """
        run_id, token, store = self.bridge._begin_run(
            "s1", "sales", _context(run_id="handle-1")
        )

        self.assertEqual(run_id, "handle-1")
        self.assertIsNotNone(self.store.get_run("handle-1"))
        self.bridge._end_run(store, run_id, token, "done")

    def test_parent_can_be_named_when_it_cannot_be_inherited(self):
        """Context variables do not cross threads, so a run handed to another
        thread has to be told who its parent is.
        """
        parent_id, parent_token, parent_store = self.bridge._begin_run(
            "s1", "sales", None
        )
        # Leaving the parent's scope stands in for arriving on another thread,
        # where the ambient id reads as empty.
        self.bridge._end_run(parent_store, parent_id, parent_token, "done")
        self.assertIsNone(current_agent_run_id())

        child_id, child_token, child_store = self.bridge._begin_run(
            "s2", "support", _context(parent_run_id=parent_id)
        )

        self.assertEqual(self.store.get_run(child_id)["parent_run_id"], parent_id)
        self.assertEqual(
            [c["run_id"] for c in self.store.list_runs(parent_run_id=parent_id)],
            [child_id],
        )
        self.bridge._end_run(child_store, child_id, child_token, "done")

    def test_an_explicit_parent_wins_over_the_ambient_one(self):
        outer_id, outer_token, outer_store = self.bridge._begin_run("s1", "sales", None)

        child_id, child_token, child_store = self.bridge._begin_run(
            "s2", "support", _context(parent_run_id="somewhere-else")
        )

        self.assertEqual(
            self.store.get_run(child_id)["parent_run_id"], "somewhere-else"
        )
        self.bridge._end_run(child_store, child_id, child_token, "done")
        self.bridge._end_run(outer_store, outer_id, outer_token, "done")

    def test_external_task_handle_is_carried_from_the_context(self):
        run_id, token, store = self.bridge._begin_run(
            "s1", "sales", _context(task_id="T-1", task_source="board")
        )

        run = self.store.get_run(run_id)
        self.assertEqual(run["task_id"], "T-1")
        self.assertEqual(run["task_source"], "board")
        self.bridge._end_run(store, run_id, token, "done")

    def test_a_native_turn_leaves_the_task_handle_empty(self):
        run_id, token, store = self.bridge._begin_run("s1", "sales", _context())

        run = self.store.get_run(run_id)
        self.assertEqual(run["task_id"], "")
        self.assertEqual(run["task_source"], "")
        self.bridge._end_run(store, run_id, token, "done")

    def test_messages_written_during_the_run_carry_its_id(self):
        run_id, token, store = self.bridge._begin_run("s1", "sales", None)
        # No explicit run_id: the store reads the ambient one _begin_run set.
        self.store.append_messages("s1", [{"role": "user", "content": "hi"}])
        self.bridge._end_run(store, run_id, token, "done")

        stored = self.store.list_runs(session_id="s1")
        self.assertEqual([r["run_id"] for r in stored], [run_id])

    def test_a_store_that_cannot_record_does_not_break_the_turn(self):
        """Bookkeeping is never allowed to fail a reply."""

        class _Broken:
            def create_run(self, *a, **kw):
                raise RuntimeError("disk full")

        bridge = _Bridge(_Broken())
        run_id, token, store = bridge._begin_run("s1", "sales", None)

        self.assertIsNone(run_id)
        self.assertIsNone(token)
        self.assertIsNone(store)
        # No ambient id was set, so nothing leaks into the next turn.
        self.assertIsNone(current_agent_run_id())
        # And closing a run that was never opened is a no-op, not a crash.
        bridge._end_run(store, run_id, token, "done")

    def test_the_ambient_id_is_restored_even_if_closing_fails(self):
        class _HalfBroken:
            def create_run(self, *a, **kw):
                return True

            def finish_run(self, *a, **kw):
                raise RuntimeError("gone")

        bridge = _Bridge(_HalfBroken())
        with identity_scope(run_id="outer"):
            run_id, token, store = bridge._begin_run("s1", "sales", None)
            self.assertEqual(current_agent_run_id(), run_id)
            bridge._end_run(store, run_id, token, "done")
            # finish_run blew up, but the scope was still unwound.
            self.assertEqual(current_agent_run_id(), "outer")


if __name__ == "__main__":
    unittest.main()
