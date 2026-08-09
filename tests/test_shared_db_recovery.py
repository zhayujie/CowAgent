# encoding:utf-8
"""
Regression tests for conversation history surviving memory-index recovery.

`ConversationStore` (sessions / messages) and `MemoryStorage` (chunks / files /
FTS5) share a single SQLite file, `memory/long-term/index.db`. Only the memory
side is re-derivable from the workspace, so recovering it must never take the
conversation history down with it — the failure mode being pinned here is
"no such table: sessions" after the memory index repaired itself.
"""
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.conversation_store import ConversationStore
from agent.memory.storage import MemoryChunk, MemoryStorage


class TestSharedDbRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "index.db"
        # These cases corrupt databases on purpose. Their recovery logging is
        # indistinguishable from a real incident, and pytest shares run.log
        # with the running app, so keep it out of the file.
        self._log = logging.getLogger("log")
        self._log_level = self._log.level
        self._log.setLevel(logging.CRITICAL + 1)

    def tearDown(self):
        self._log.setLevel(self._log_level)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers -------------------------------------------------------

    def _store_with_history(self) -> ConversationStore:
        store = ConversationStore(self.db)
        store.append_messages(
            "s1",
            [{"role": "user", "content": "hello"},
             {"role": "assistant", "content": "hi"}],
            channel_type="web",
        )
        return store

    def _memory_with_chunk(self) -> MemoryStorage:
        storage = MemoryStorage(self.db)
        storage.save_chunk(MemoryChunk(
            id="c1", user_id=None, scope="shared", source="memory",
            path="a.md", start_line=1, end_line=1, text="hello world",
            embedding=None, hash="h1",
        ))
        storage.conn.commit()
        return storage

    def _quarantined(self):
        return [p.name for p in self.tmp.iterdir() if ".corrupt-" in p.name]

    # -- tests ---------------------------------------------------------

    def test_damaged_fts5_index_does_not_drop_conversation_history(self):
        """Since SQLite 3.44 integrity_check also validates FTS5 content, so a
        stale search index reports as a failure. It must be rebuilt in place."""
        store = self._store_with_history()
        storage = self._memory_with_chunk()
        storage.close()

        raw = sqlite3.connect(self.db)
        raw.execute(
            "DELETE FROM chunks_fts_data WHERE id=(SELECT MAX(id) FROM chunks_fts_data)"
        )
        raw.commit()
        self.assertNotEqual(
            raw.execute("PRAGMA integrity_check").fetchone()[0], "ok"
        )
        raw.close()

        recovered = MemoryStorage(self.db)
        self.assertEqual(
            recovered.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok"
        )
        self.assertEqual(
            recovered.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 1
        )
        recovered.close()

        self.assertEqual(len(store.load_messages("s1")), 2)
        self.assertEqual(self._quarantined(), [])

    def test_corrupt_database_is_quarantined_not_deleted(self):
        store = ConversationStore(self.db)
        for i in range(300):
            store.append_messages(
                f"s{i}", [{"role": "user", "content": "x" * 400}], channel_type="web"
            )
        MemoryStorage(self.db).close()
        sqlite3.connect(self.db).execute("PRAGMA journal_mode=DELETE")

        with open(self.db, "r+b") as f:
            f.seek(4096 * 3)
            f.write(b"\x00" * 4096)

        MemoryStorage(self.db).close()
        self.assertEqual(len(self._quarantined()), 1)

    def test_unreadable_database_is_quarantined_not_deleted(self):
        self._store_with_history()
        MemoryStorage(self.db).close()

        with open(self.db, "r+b") as f:
            f.seek(0)
            f.write(b"GARBAGE!" * 2)

        MemoryStorage(self.db).close()
        self.assertEqual(len(self._quarantined()), 1)

    def test_store_recreates_schema_when_db_file_is_replaced(self):
        """A replaced file used to leave the process-wide store permanently
        broken, silently dropping every message for the rest of its lifetime."""
        store = self._store_with_history()

        for name in ("", "-wal", "-shm"):
            Path(f"{self.db}{name}").unlink(missing_ok=True)
        MemoryStorage(self.db).close()  # recreates the file with memory tables only

        store.append_messages(
            "s2", [{"role": "user", "content": "after"}], channel_type="web"
        )
        self.assertEqual(len(store.load_messages("s2")), 1)
        self.assertEqual(store.list_sessions()["total"], 1)

    def test_opening_a_database_from_before_the_current_schema(self):
        """Every other case here builds the schema from scratch, so nothing was
        exercising the upgrade path. Adding an index over a migrated column to
        the initial DDL broke it: on an existing database the CREATE TABLE is a
        no-op, the column is not there yet, and one failing statement aborts the
        rest of the script, so the tables after it were never created and the
        store would not open at all. Real histories only ever arrive this way.
        """
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                channel_type TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                last_active INTEGER NOT NULL,
                msg_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE (session_id, seq)
            );
            """
        )
        conn.execute("INSERT INTO sessions VALUES ('s1', 'web', 1, 1, 1)")
        conn.execute(
            "INSERT INTO messages (session_id, seq, role, content, created_at) "
            "VALUES ('s1', 0, 'user', '\"hello\"', 1)"
        )
        conn.commit()
        conn.close()

        store = ConversationStore(self.db)

        self.assertEqual(store.list_sessions()["total"], 1)
        self.assertEqual(len(store.load_messages("s1")), 1)
        store.append_messages("s1", [{"role": "assistant", "content": "hi"}])
        self.assertEqual(len(store.load_messages("s1")), 2)

        with sqlite3.connect(self.db) as raw:
            columns = {row[1] for row in raw.execute("PRAGMA table_info(messages)")}
            objects = {
                row[0]
                for row in raw.execute("SELECT name FROM sqlite_master")
            }
        self.assertIn("run_id", columns)
        self.assertIn("runs", objects)
        self.assertIn("idx_messages_run", objects)

        ConversationStore(self.db)  # reopening an upgraded database is a no-op

    def test_transient_error_is_not_treated_as_corruption(self):
        """sqlite3.OperationalError subclasses DatabaseError, so "database is
        locked" must not be mistaken for corruption."""
        self._store_with_history()
        MemoryStorage(self.db).close()

        calls = {"n": 0}

        class LockedOnce(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if sql == "PRAGMA integrity_check" and calls["n"] == 0:
                    calls["n"] += 1
                    raise sqlite3.OperationalError("database is locked")
                return super().execute(sql, *args, **kwargs)

        real_connect = sqlite3.connect

        def connect_locked(*args, **kwargs):
            kwargs["factory"] = LockedOnce
            return real_connect(*args, **kwargs)

        with unittest.mock.patch("sqlite3.connect", connect_locked):
            storage = MemoryStorage(self.db)

        self.assertEqual(calls["n"], 1)
        self.assertEqual(self._quarantined(), [])
        self.assertEqual(
            storage.conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0], 1
        )
        storage.close()


if __name__ == "__main__":
    unittest.main()
