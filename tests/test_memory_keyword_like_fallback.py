# encoding:utf-8
"""search_keyword falls back to LIKE when an FTS5 stage ran and found nothing."""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.storage import MemoryChunk, MemoryStorage


@pytest.fixture
def storage(tmp_path):
    s = MemoryStorage(tmp_path / "index.db")
    # Let the background index repair finish before the test breaks the index.
    for t in threading.enumerate():
        if t.name == "memory-db-maintenance":
            t.join(timeout=10)
    s.save_chunk(MemoryChunk(
        id="c1", user_id=None, scope="shared", source="memory",
        path="memory/shared/finance.md", start_line=1, end_line=1,
        text="The invoice for March was paid by the client.",
        embedding=None, hash="h1",
    ))
    s.conn.commit()
    s.trigram_fts5_available = False
    yield s
    s.close()


def test_ascii_query_uses_like_when_fts_index_is_broken(storage):
    storage.conn.execute("DROP TABLE IF EXISTS chunks_fts")
    storage.conn.commit()

    results = storage.search_keyword("invoice")

    assert [r.path for r in results] == ["memory/shared/finance.md"]


def test_the_best_matching_chunk_survives_a_small_limit(storage):
    """Ranking must happen before the LIMIT, not after.

    The multi-word chunk sits last in scan order; with LIMIT applied to an
    unordered scan and a limit smaller than the match count, it never reached
    the Python-side scoring and single-word matches filled the results.
    """
    for i in range(8):
        storage.save_chunk(MemoryChunk(
            id=f"noise-{i}", user_id=None, scope="shared", source="memory",
            path=f"memory/shared/noise-{i}.md", start_line=1, end_line=1,
            text=f"Note {i} mentions receipt only.", embedding=None, hash=f"hn{i}",
        ))
    storage.save_chunk(MemoryChunk(
        id="best", user_id=None, scope="shared", source="memory",
        path="memory/shared/best.md", start_line=1, end_line=1,
        text="The receipt and the filed folder are stored together.",
        embedding=None, hash="hbest",
    ))
    storage.conn.commit()
    storage.conn.execute("DROP TABLE IF EXISTS chunks_fts")
    storage.conn.commit()
    storage.trigram_fts5_available = False

    results = storage._search_like("receipt filed", None, ["shared"], 5)

    assert results, "the LIKE fallback found nothing"
    assert results[0].path == "memory/shared/best.md", (
        "the two-word match was cut by the storage-order LIMIT"
    )
