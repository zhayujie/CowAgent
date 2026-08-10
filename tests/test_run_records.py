# encoding:utf-8
"""Task records: the run id format, and messages knowing which task they were part of."""

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.conversation_store import ConversationStore, new_run_id
from common.runtime_identity import identity_scope


class TestRunIds(unittest.TestCase):
    def test_run_ids_sort_in_time_order(self):
        """Sortable on purpose: the run directories come out in order without a
        query, and a retention sweep selects old ones by prefix."""
        ids = [new_run_id() for _ in range(50)]

        self.assertEqual(len(set(ids)), len(ids))
        for run_id in ids:
            self.assertRegex(run_id, r"^r-\d{13,}-[0-9a-f]{4}$")

        early, late = new_run_id(), None
        while late is None or late[:15] == early[:15]:
            late = new_run_id()
        self.assertLess(early, late)


class TestMessagesCarryTheirRun(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = ConversationStore(self.tmp / "index.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stored_run_ids(self, session_id: str):
        with __import__("sqlite3").connect(self.tmp / "index.db") as conn:
            return [
                row[0]
                for row in conn.execute(
                    "SELECT run_id FROM messages WHERE session_id = ? ORDER BY seq",
                    (session_id,),
                )
            ]

    def test_the_ambient_run_is_picked_up_without_an_argument(self):
        """Callers deep in the loop do not thread a run id down by hand, which
        is the whole point of the ambient identity."""
        with identity_scope(run_id="r-1-aaaa"):
            self.store.append_messages("s1", [{"role": "user", "content": "hi"}])
        self.store.append_messages("s1", [{"role": "assistant", "content": "no run"}])

        self.assertEqual(self._stored_run_ids("s1"), ["r-1-aaaa", ""])

    def test_an_explicit_run_wins_over_the_ambient_one(self):
        with identity_scope(run_id="r-1-aaaa"):
            self.store.append_messages(
                "s1", [{"role": "user", "content": "hi"}], run_id="r-2-bbbb"
            )

        self.assertEqual(self._stored_run_ids("s1"), ["r-2-bbbb"])

    def test_stamping_does_not_disturb_what_was_already_stored(self):
        self.store.append_messages("s1", [{"role": "user", "content": "hi"}])
        with identity_scope(run_id="r-1-aaaa"):
            self.store.append_messages("s1", [{"role": "assistant", "content": "yo"}])

        loaded = self.store.load_messages("s1")
        self.assertEqual([m["role"] for m in loaded], ["user", "assistant"])
        history = self.store.load_history_page("s1")["messages"]
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual([m["content"] for m in history], ["hi", "yo"])


class TestTheRunsIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = ConversationStore(self.tmp / "index.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_run_goes_from_running_to_done(self):
        self.store.start_run(
            "r-1-aaaa", agent_id="alpha", session_id="s1",
            channel_type="web", goal="look something up", model="claude-sonnet-5",
        )
        opened = self.store.get_run("r-1-aaaa")
        self.assertEqual(opened["status"], "running")
        self.assertIsNone(opened["ended_at"])
        self.assertEqual(opened["trigger_type"], "message")

        self.store.finish_run("r-1-aaaa", status="done", steps=4, subagents=2)
        closed = self.store.get_run("r-1-aaaa")
        self.assertEqual(closed["status"], "done")
        self.assertEqual((closed["steps"], closed["subagents"]), (4, 2))
        self.assertIsNotNone(closed["ended_at"])

    def test_an_unknown_status_is_refused(self):
        """The value set is the state machine. Letting anything through means
        the list filters silently stop matching."""
        self.store.start_run("r-1-aaaa")
        with self.assertRaises(ValueError):
            self.store.finish_run("r-1-aaaa", status="finished")

    def test_extras_merge_instead_of_overwriting(self):
        self.store.start_run("r-1-aaaa", extras={"from_open": 1})
        self.store.finish_run("r-1-aaaa", extras={"from_close": 2})
        self.assertEqual(
            self.store.get_run("r-1-aaaa")["extras"], {"from_open": 1, "from_close": 2}
        )

    def test_listing_top_level_runs_leaves_sub_agents_inside_their_parent(self):
        self.store.start_run("r-1-aaaa", session_id="s1")
        self.store.start_run("r-2-bbbb", session_id="s1", parent_run_id="r-1-aaaa")
        self.store.start_run("r-3-cccc", session_id="s1", parent_run_id="r-1-aaaa")
        self.store.start_run("r-4-dddd", session_id="s2")

        top = self.store.list_runs(parent_run_id="")
        self.assertEqual({r["run_id"] for r in top["runs"]}, {"r-1-aaaa", "r-4-dddd"})

        children = self.store.list_runs(parent_run_id="r-1-aaaa")
        self.assertEqual(
            sorted(r["run_id"] for r in children["runs"]), ["r-2-bbbb", "r-3-cccc"]
        )
        self.assertEqual(self.store.list_runs(session_id="s2")["total"], 1)

    def test_deleting_index_rows_for_a_retention_sweep(self):
        self.store.start_run("r-1-aaaa")
        self.store.start_run("r-2-bbbb")
        self.assertEqual(self.store.delete_runs(["r-1-aaaa", "nope"]), 1)
        self.assertIsNone(self.store.get_run("r-1-aaaa"))
        self.assertIsNotNone(self.store.get_run("r-2-bbbb"))


class TestOpeningARun(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = ConversationStore(self.tmp / "index.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_run_inside_another_nests_under_it(self):
        """Nobody passes a parent down: a sub agent runs inside its parent's
        scope, so it reads the parent off the ambient identity."""
        from agent.memory.run_records import open_run

        parent = open_run("parent task", store=self.store)
        with parent.scope():
            child = open_run("child task", trigger_type="delegate", store=self.store)

        self.assertEqual(parent.parent_run_id, "")
        self.assertEqual(child.parent_run_id, parent.run_id)
        self.assertEqual(
            self.store.get_run(child.run_id)["trigger_type"], "delegate"
        )

    def test_no_store_means_no_record_not_the_default_one(self):
        """A caller that knows which database it wants and could not get it must
        land nowhere, not in whichever one happens to resolve: that is how a test
        run wrote its fixtures into a live database.
        """
        from agent.memory.run_records import open_run

        resolved = []

        def explode():
            resolved.append(True)
            raise AssertionError("resolved a store when none was wanted")

        import agent.memory as memory_module

        original = memory_module.get_conversation_store
        memory_module.get_conversation_store = explode
        try:
            run = open_run("a task", store=None)
        finally:
            memory_module.get_conversation_store = original

        self.assertTrue(run.run_id)
        self.assertEqual(resolved, [])
        run.close()

    def test_a_failure_to_record_does_not_reach_the_caller(self):
        """A trace that can break the thing it describes is worse than none."""
        from agent.memory.run_records import record_run

        class Broken:
            def start_run(self, *a, **kw):
                raise RuntimeError("disk full")

            def finish_run(self, *a, **kw):
                raise RuntimeError("still full")

        with record_run("a task", store=Broken()) as run:
            self.assertTrue(run.run_id)

    def test_the_scope_is_entered_even_when_nothing_could_be_recorded(self):
        from agent.memory.run_records import record_run
        from common.runtime_identity import current_identity

        class Broken:
            def start_run(self, *a, **kw):
                raise RuntimeError("disk full")

        with record_run("a task", store=Broken()) as run:
            self.assertEqual(current_identity().run_id, run.run_id)

    def test_an_exception_closes_the_run_as_failed(self):
        from agent.memory.run_records import record_run

        with self.assertRaises(ValueError):
            with record_run("a task", store=self.store) as run:
                run_id = run.run_id
                raise ValueError("nope")

        closed = self.store.get_run(run_id)
        self.assertEqual(closed["status"], "failed")
        self.assertIn("nope", closed["error"])

    def test_steps_and_sub_agents_are_read_off_the_messages(self):
        from agent.memory.run_records import summarize_messages

        counted = summarize_messages([
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "subagent", "input": {"tasks": [{}, {}]}},
            ]},
            {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "read", "input": {}},
            ]},
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        ])

        self.assertEqual(counted, {"steps": 3, "subagents": 2})

    def test_the_goal_is_one_line_not_the_whole_prompt(self):
        from agent.memory.run_records import open_run

        run = open_run("Look into this\n\nwith lots of\ncontext after", store=self.store)
        self.assertEqual(self.store.get_run(run.run_id)["goal"], "Look into this")


if __name__ == "__main__":
    unittest.main()
