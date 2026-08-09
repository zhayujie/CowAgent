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


if __name__ == "__main__":
    unittest.main()
