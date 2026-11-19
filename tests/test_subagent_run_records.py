"""A spawned sub agent gets its own run row, parented to the turn that spawned it.

These go through runner._open_run / _close_run against a real store rather than
running a whole sub agent, which needs a live model.
"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.conversation_store import ConversationStore
from agent.subagent import runner
from common.runtime_identity import identity_scope


def _template(name="general-purpose"):
    return SimpleNamespace(name=name)


class SubagentRunRecordTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = self._tmp.name
        # runner resolves the store from the parent's workspace; point that at
        # a temporary one so nothing touches a real ~/cow database.
        self.store = ConversationStore(
            Path(self.workspace) / "memory" / "long-term" / "index.db"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _parent(self, **kwargs):
        defaults = {
            "workspace_dir": self.workspace,
            "_current_agent_id": "sales",
            "_current_session_id": "sess-1",
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_spawn_is_recorded_under_the_parent_run(self):
        with identity_scope(run_id="parent-run"):
            store = runner._open_run(self._parent(), "child-1", _template())
        self.assertIsNotNone(store)

        run = self.store.get_run("child-1")
        self.assertIsNotNone(run)
        self.assertEqual(run["parent_run_id"], "parent-run")
        self.assertEqual(run["agent_id"], "sales")
        self.assertEqual(run["session_id"], "sess-1")
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["extras"], {"subagent_type": "general-purpose"})

        children = self.store.list_runs(parent_run_id="parent-run")
        self.assertEqual([c["run_id"] for c in children], ["child-1"])

    def test_completed_spawn_is_closed_as_done(self):
        store = runner._open_run(self._parent(), "child-1", _template())
        runner._close_run(store, "child-1", {"status": "completed"})

        run = self.store.get_run("child-1")
        self.assertEqual(run["status"], "done")
        self.assertIsNotNone(run["ended_at"])

    def test_failed_spawn_keeps_its_error(self):
        store = runner._open_run(self._parent(), "child-1", _template())
        runner._close_run(
            store, "child-1", {"status": "failed", "error": "tool exploded"}
        )

        run = self.store.get_run("child-1")
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error"], "tool exploded")

    def test_cancelled_spawn_is_distinct_from_failed(self):
        store = runner._open_run(self._parent(), "child-1", _template())
        runner._close_run(store, "child-1", {"status": "cancelled"})

        self.assertEqual(self.store.get_run("child-1")["status"], "cancelled")

    def test_a_parent_without_a_workspace_is_not_recorded(self):
        """No workspace means no database to attribute the spawn to. Guessing a
        global one would write into an unrelated workspace's history."""
        store = runner._open_run(
            self._parent(workspace_dir=None), "child-1", _template()
        )

        self.assertIsNone(store)
        # Closing a run that was never opened is a no-op rather than a crash.
        runner._close_run(store, "child-1", {"status": "completed"})

    def test_a_top_level_spawn_has_no_parent(self):
        store = runner._open_run(self._parent(), "child-1", _template())
        self.assertEqual(self.store.get_run("child-1")["parent_run_id"], "")
        runner._close_run(store, "child-1", {"status": "completed"})

    def _stopped_run(self, *, cancel=False, late_error=False, slow_open=False):
        entered = threading.Event()
        release = threading.Event()
        worker_finished = threading.Event()
        stop = threading.Event()
        results = []
        failures = []
        original_open = runner._open_run
        original_one = runner._run_one

        def open_run(*args):
            if slow_open:
                entered.set()
                release.wait(5)
            return original_open(*args)

        class Child:
            def run_stream(self, *args, **kwargs):
                entered.set()
                release.wait(5)
                if late_error:
                    raise RuntimeError("late failure")
                return "late answer"

        def run_one(*args):
            try:
                return original_one(*args)
            finally:
                worker_finished.set()

        def supervise():
            try:
                results.extend(runner.run_tasks(
                    self._parent(), [runner.SubagentTask("test")],
                    {"general-purpose": _template()},
                    runner.SubagentSettings(timeout_seconds=5 if cancel else 0.2),
                    cancel_event=stop,
                ))
            except Exception as exc:
                failures.append(exc)

        with patch.object(runner, "_open_run", open_run), \
                patch.object(runner, "_build_child", return_value=Child()), \
                patch.object(runner, "_run_one", run_one):
            supervisor = threading.Thread(target=supervise)
            supervisor.start()
            try:
                self.assertTrue(entered.wait(3))
                if cancel:
                    stop.set()
                supervisor.join(3)
                self.assertFalse(supervisor.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(results[0]["status"], "cancelled" if cancel else "timeout")
                if not slow_open:
                    row = self.store.list_runs()[0]
                    self.assertEqual(row["status"], "cancelled" if cancel else "timeout")
                    self.assertEqual(row["error"], results[0]["error"])
                    self.assertIsNotNone(row["ended_at"])
                release.set()
                self.assertTrue(worker_finished.wait(3))
                row_after = self.store.list_runs()[0]
                self.assertEqual(row_after["status"], "cancelled" if cancel else "timeout")
                self.assertEqual(row_after["error"], results[0]["error"])
                self.assertIsNotNone(row_after["ended_at"])
                if not slow_open:
                    self.assertEqual(row_after, row)
            finally:
                release.set()
                supervisor.join(3)
                worker_finished.wait(3)

    def test_timeout_is_persisted_before_worker_returns(self):
        self._stopped_run()

    def test_late_exception_does_not_replace_timeout(self):
        self._stopped_run(late_error=True)

    def test_parent_cancel_is_persisted_before_worker_returns(self):
        self._stopped_run(cancel=True)

    def test_timeout_while_opening_run_is_not_lost(self):
        self._stopped_run(slow_open=True)


if __name__ == "__main__":
    unittest.main()
