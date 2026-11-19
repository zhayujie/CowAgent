"""The retrieval-hit boost is opt-in, bounded, and stays out of the way when off."""

import sqlite3
from types import SimpleNamespace

from agent.memory.manager import MemoryManager
from agent.memory.storage import MemoryChunk, MemoryStorage, SearchResult


def _storage(tmp_path):
    storage = MemoryStorage(tmp_path / "index.db")
    for i, path in enumerate(["a.md", "b.md"]):
        storage.save_chunk(MemoryChunk(
            id=f"c{i}", user_id=None, scope="shared", source="memory", path=path,
            start_line=1, end_line=2, text=path, embedding=None, hash=f"h{i}"))
    return storage


def _manager(storage, weight):
    manager = MemoryManager.__new__(MemoryManager)
    manager.storage = storage
    manager.config = SimpleNamespace(hit_boost_weight=weight, hit_boost_max=1.25)
    return manager


def _results():
    return [SearchResult("a.md", 1, 2, 0.50, "", "memory"),
            SearchResult("b.md", 1, 2, 0.48, "", "memory")]


def test_off_by_default_keeps_order(tmp_path):
    manager = _manager(_storage(tmp_path), 0.0)
    assert not manager._hit_boost_enabled()
    assert [r.path for r in manager._apply_hit_boost(_results())] == ["a.md", "b.md"]


def test_frequent_hits_reorder_near_ties_within_the_cap(tmp_path):
    storage = _storage(tmp_path)
    for _ in range(8):
        storage.record_hits([(None, "b.md", 1, 2)])
    boosted = _manager(storage, 0.05)._apply_hit_boost(_results())
    assert [r.path for r in boosted] == ["b.md", "a.md"]
    assert boosted[0].score <= 0.48 * 1.25
    assert storage.get_hit_stats([(None, "b.md", 1, 2)])[(None, "b.md", 1, 2)][0] == 8


def test_old_chunks_table_gains_the_hit_columns(tmp_path):
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE chunks (id TEXT PRIMARY KEY, user_id TEXT, scope TEXT, source TEXT, "
                 "path TEXT, start_line INTEGER, end_line INTEGER, text TEXT, embedding TEXT, "
                 "hash TEXT, metadata TEXT, created_at INTEGER, updated_at INTEGER)")
    conn.commit()
    conn.close()
    storage = MemoryStorage(db)
    cols = {row[1] for row in storage.conn.execute("PRAGMA table_info(chunks)")}
    assert {"hit_count", "last_hit_at"} <= cols
