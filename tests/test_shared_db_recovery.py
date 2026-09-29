# encoding:utf-8
"""
Regression tests for conversation history surviving memory-index checks.

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
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.conversation_store import ConversationStore
from agent.memory import storage as storage_mod
from agent.memory.storage import MemoryChunk, MemoryStorage


def _wait_for_maintenance():
    for t in threading.enumerate():
        if t.name == "memory-db-maintenance":
            t.join(timeout=10)


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

    def _scan_again(self):
        """Forget this file was scanned, so the next open starts a new scan."""
        storage_mod._maintenance_started.discard(str(self.db))

    @staticmethod
    def _wait_for_scan():
        _wait_for_maintenance()

    def _corrupt_interior_page(self):
        store = ConversationStore(self.db)
        for i in range(300):
            store.append_messages(
                f"s{i}", [{"role": "user", "content": "x" * 400}], channel_type="web"
            )
        MemoryStorage(self.db).close()
        self._wait_for_scan()
        sqlite3.connect(self.db).execute("PRAGMA journal_mode=DELETE")
        with open(self.db, "r+b") as f:
            f.seek(4096 * 3)
            f.write(b"\x00" * 4096)

    # -- tests ---------------------------------------------------------

    def test_damaged_fts5_index_is_rebuilt_in_place(self):
        """Since SQLite 3.44 integrity_check also validates FTS5 content, so a
        stale search index reports as a failure. It must be rebuilt in place."""
        store = self._store_with_history()
        storage = self._memory_with_chunk()
        storage.close()
        self._wait_for_scan()

        raw = sqlite3.connect(self.db)
        raw.execute(
            "DELETE FROM chunks_fts_data WHERE id=(SELECT MAX(id) FROM chunks_fts_data)"
        )
        raw.commit()
        self.assertNotEqual(
            raw.execute("PRAGMA integrity_check").fetchone()[0], "ok"
        )
        raw.close()

        self._scan_again()
        recovered = MemoryStorage(self.db)
        self._wait_for_scan()
        self.assertEqual(
            recovered.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok"
        )
        self.assertEqual(
            recovered.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 1
        )
        recovered.close()

        self.assertEqual(len(store.load_messages("s1")), 2)
        self.assertEqual(self._quarantined(), [])

    def test_corrupt_database_is_left_in_place(self):
        """The conversation history lives in this file: damage is reported,
        never answered by moving the file away."""
        self._corrupt_interior_page()

        self._scan_again()
        MemoryStorage(self.db).close()
        self._wait_for_scan()
        MemoryStorage(self.db).close()

        self.assertTrue(self.db.exists())
        self.assertEqual(self._quarantined(), [])

    def test_integrity_scan_runs_once_and_never_on_the_open_path(self):
        """A scan of a large file used to hold up every session's first message
        for minutes."""
        calls = []
        release = threading.Event()

        def slow_scan(conn):
            calls.append(1)
            release.wait(10)
            return None

        with unittest.mock.patch.object(
            MemoryStorage, "_integrity_report", staticmethod(slow_scan)
        ):
            started = time.monotonic()
            for _ in range(3):
                MemoryStorage(self.db).close()
            elapsed = time.monotonic() - started
            release.set()
            self._wait_for_scan()

        self.assertLess(elapsed, 5)
        self.assertEqual(len(calls), 1)

    def test_open_path_never_reads_the_whole_index(self):
        """Every statement run while opening must cost the same on a 1GB file
        as on an empty one."""
        storage = self._memory_with_chunk()
        storage.close()
        self._wait_for_scan()
        # Flag both indexes for a rebuild, the worst case for an open.
        raw = sqlite3.connect(self.db)
        raw.execute("DELETE FROM _meta WHERE key='trigram_backfill_done'")
        raw.execute("INSERT OR REPLACE INTO _meta(key, value) VALUES('fts_rebuild_pending', '1')")
        raw.commit()
        raw.close()

        statements = []
        real_open = MemoryStorage._open_conn

        def traced_open(this):
            conn = real_open(this)
            conn.set_trace_callback(statements.append)
            return conn

        self._scan_again()
        with unittest.mock.patch.object(MemoryStorage, "_open_conn", traced_open), \
                unittest.mock.patch.object(MemoryStorage, "_schedule_maintenance"):
            MemoryStorage(self.db).close()

        heads = [" ".join(sql.split())[:60] for sql in statements]
        scans = [
            head for head in heads
            if ("COUNT(" in head and "sqlite_master" not in head)
            or "_check" in head or "MATCH" in head
            or head.startswith(("INSERT INTO chunks_fts", "DROP TABLE IF EXISTS chunks"))
        ]
        self.assertEqual(scans, [])
        self.assertTrue(any(h.startswith("CREATE TABLE IF NOT EXISTS chunks") for h in heads))

    def test_search_index_backfill_does_not_hold_up_the_open(self):
        storage = self._memory_with_chunk()
        storage.close()
        self._wait_for_scan()
        raw = sqlite3.connect(self.db)
        raw.execute("DELETE FROM _meta WHERE key='trigram_backfill_done'")
        raw.commit()
        raw.close()

        release = threading.Event()
        real_refill = MemoryStorage._refill_index

        def slow_refill(conn, table):
            release.wait(10)
            real_refill(conn, table)

        self._scan_again()
        with unittest.mock.patch.object(
            MemoryStorage, "_refill_index", staticmethod(slow_refill)
        ):
            started = time.monotonic()
            storage = MemoryStorage(self.db)
            elapsed = time.monotonic() - started
            release.set()
            self._wait_for_scan()

        self.assertLess(elapsed, 5)
        if storage.trigram_fts5_available:
            self.assertEqual(
                [r.path for r in storage._search_fts5_trigram("hello", None, ["shared"], 10)],
                ["a.md"],
            )
        storage.close()

    def test_unreadable_database_is_left_in_place(self):
        self._store_with_history()
        MemoryStorage(self.db).close()
        self._wait_for_scan()

        with open(self.db, "r+b") as f:
            f.seek(0)
            f.write(b"GARBAGE!" * 2)

        with self.assertRaises(sqlite3.DatabaseError):
            MemoryStorage(self.db)
        with open(self.db, "rb") as f:
            self.assertEqual(f.read(16), b"GARBAGE!" * 2)
        self.assertEqual(self._quarantined(), [])

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

    def test_transient_error_is_not_treated_as_corruption(self):
        """sqlite3.OperationalError subclasses DatabaseError, so "database is
        locked" must not be mistaken for corruption."""
        self._store_with_history()
        MemoryStorage(self.db).close()
        self._wait_for_scan()

        calls = {"n": 0}

        class LockedOnce(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                # Either check pragma; which one runs is a performance choice,
                # and this is about how its failure is classified.
                if sql.startswith("PRAGMA ") and sql.endswith("_check") and calls["n"] == 0:
                    calls["n"] += 1
                    raise sqlite3.OperationalError("database is locked")
                return super().execute(sql, *args, **kwargs)

        real_connect = sqlite3.connect

        def connect_locked(*args, **kwargs):
            kwargs["factory"] = LockedOnce
            return real_connect(*args, **kwargs)

        self._scan_again()
        with unittest.mock.patch("sqlite3.connect", connect_locked):
            storage = MemoryStorage(self.db)
            self._wait_for_scan()

        self.assertEqual(calls["n"], 1)
        self.assertEqual(self._quarantined(), [])
        self.assertEqual(
            storage.conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0], 1
        )
        storage.close()


class TestTrigramUpdateTrigger(unittest.TestCase):
    """The trigram FTS5 index must survive updates to an existing chunk.

    External-content FTS5 corrupts ("database disk image is malformed") when an
    UPDATE trigger rewrites the row with a bare "UPDATE ... SET" instead of the
    delete+insert pattern. These cases pin the fix and its migration.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "index.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _chunk(self, text: str, embedding=None) -> MemoryChunk:
        return MemoryChunk(
            id="c1", user_id=None, scope="shared", source="memory",
            path="a.md", start_line=1, end_line=1, text=text,
            embedding=embedding, hash="h",
        )

    def test_updating_chunk_keeps_trigram_index_healthy(self):
        storage = MemoryStorage(self.db)
        if not storage.trigram_fts5_available:
            self.skipTest("trigram FTS5 unavailable in this SQLite build")
        storage.save_chunk(self._chunk("人工智能教程"))
        # Would raise "database disk image is malformed" with the old trigger.
        storage.save_chunk(self._chunk("机器学习笔记"))
        self.assertEqual(
            [r.path for r in storage.search_keyword("机器学习")], ["a.md"]
        )
        # Old tokens must be gone from the index after the update.
        self.assertEqual(storage.search_keyword("人工智能教程"), [])
        storage.close()

    def test_legacy_update_trigger_is_migrated_on_open(self):
        storage = MemoryStorage(self.db)
        if not storage.trigram_fts5_available:
            self.skipTest("trigram FTS5 unavailable in this SQLite build")
        storage.save_chunk(self._chunk("深度学习入门"))
        storage.close()

        # Downgrade to the legacy buggy trigger to simulate an old database.
        conn = sqlite3.connect(str(self.db))
        conn.execute("DROP TRIGGER IF EXISTS chunks_trigram_au")
        conn.execute(
            "CREATE TRIGGER chunks_trigram_au AFTER UPDATE ON chunks BEGIN "
            "UPDATE chunks_fts_trigram SET text=new.text, id=new.id, "
            "user_id=new.user_id, path=new.path, source=new.source, "
            "scope=new.scope WHERE rowid=new.rowid; END"
        )
        conn.commit()
        conn.close()

        storage = MemoryStorage(self.db)
        _wait_for_maintenance()
        trigger_sql = storage.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='chunks_trigram_au'"
        ).fetchone()[0]
        self.assertNotIn("UPDATE chunks_fts_trigram", trigger_sql)
        # Updates now work without corrupting the index.
        storage.save_chunk(self._chunk("强化学习进阶"))
        self.assertEqual(
            [r.path for r in storage.search_keyword("强化学习")], ["a.md"]
        )
        self.assertEqual(storage.search_keyword("深度学习入门"), [])
        storage.close()


class TestTrigramTokenizerUnavailable(unittest.TestCase):
    """A database written where the trigram tokenizer exists (SQLite 3.34+)
    carries an index an older build cannot open. Its triggers fire on every
    insert, update and delete on `chunks`, so leaving them in place breaks the
    whole memory and knowledge index — every save comes back with "no such
    tokenizer: trigram" — rather than only CJK search.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "index.db"
        self._log = logging.getLogger("log")
        self._log_level = self._log.level
        self._log.setLevel(logging.CRITICAL + 1)

    def tearDown(self):
        self._log.setLevel(self._log_level)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_unopenable_trigram_index_is_detached_rather_than_breaking_writes(self):
        MemoryStorage(self.db).close()
        # Install the trigger by hand so the case is the same whether or not
        # this build's SQLite created one of its own on that first open.
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS chunks_trigram_ai AFTER INSERT ON chunks BEGIN "
            "INSERT INTO chunks_fts_trigram(rowid, text) VALUES (new.rowid, new.text); END"
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key, value) VALUES('trigram_backfill_done', '1')"
        )
        conn.commit()
        conn.close()

        def unavailable(conn):
            raise sqlite3.OperationalError("no such tokenizer: trigram")

        with unittest.mock.patch.object(MemoryStorage, "_create_trigram_objects",
                                        staticmethod(unavailable)):
            storage = MemoryStorage(self.db)

        self.assertFalse(storage.trigram_fts5_available)
        self.assertEqual(
            storage.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'chunks_trigram%'"
            ).fetchall(),
            [],
        )
        # The backfill flag has to go with them, or a later open by a build that
        # does have the tokenizer would trust an index missing every write made
        # in between.
        self.assertIsNone(
            storage.conn.execute(
                "SELECT 1 FROM _meta WHERE key = 'trigram_backfill_done'"
            ).fetchone()
        )

        # The point of all of the above: saving still works.
        storage.save_chunk(MemoryChunk(
            id="c1", user_id=None, scope="shared", source="knowledge",
            path="knowledge/notes/a.md", start_line=1, end_line=1,
            text="知识库编辑", embedding=None, hash="h",
        ))
        self.assertEqual(
            [r.path for r in storage.search_keyword("知识库编辑")],
            ["knowledge/notes/a.md"],
        )
        storage.delete_by_path("knowledge/notes/a.md")
        storage.close()


if __name__ == "__main__":
    unittest.main()
