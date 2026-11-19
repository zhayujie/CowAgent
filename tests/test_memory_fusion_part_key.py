# encoding:utf-8
"""Hard-split sibling pieces must stay separate in hybrid fusion.

A line longer than the chunk budget is split into several pieces that share
(path, start_line, end_line) — the storage layer gave them distinct ids (v3),
but the fusion layer still keyed on the triple:

- ``_rank_normalize`` let a later (worse-ranked) sibling overwrite the best
  piece's 1.0 with its own rank;
- the union of the two channels collapsed N pieces into one fusion entry,
  shrinking the candidate pool;
- hit bookkeeping (record_hits / get_hit_stats) credited every sibling for a
  hit on one piece.

These tests pin the chunk-id fusion key: siblings stay separate, the best
piece keeps its rank, and only the matched piece is credited.
"""
import os
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.manager import MemoryManager
from agent.memory.storage import MemoryChunk, MemoryStorage, SearchResult


def _manager():
    manager = MemoryManager.__new__(MemoryManager)
    manager.storage = None
    manager.config = SimpleNamespace()
    return manager


def _result(chunk_id, score):
    return SearchResult(
        path="memory/shared/long.md", start_line=1, end_line=1,
        score=score, snippet="piece", source="memory",
        user_id=None, chunk_id=chunk_id,
    )


class TestFusionKeepsSiblingsApart:

    def test_two_pieces_are_not_collapsed_and_ranks_do_not_overwrite(self):
        manager = _manager()
        vector_results = [_result("long#1", 0.9)]          # best piece, rank 1
        keyword_results = [_result("long#1", 0.8), _result("long#2", 0.7)]

        merged = manager._merge_results(vector_results, keyword_results, 0.5, 0.5)

        # Both pieces survive fusion instead of collapsing into one entry.
        self._ids = [getattr(r, "chunk_id", None) for r in merged]
        assert sorted(self._ids) == ["long#1", "long#2"]
        # The best piece keeps the top score: its vector rank (1.0) was not
        # overwritten by the keyword channel's later sibling.
        assert getattr(merged[0], "chunk_id", None) == "long#1"
        assert merged[0].score > merged[1].score


@pytest.fixture
def storage(tmp_path):
    s = MemoryStorage(tmp_path / "index.db")
    for t in threading.enumerate():
        if t.name == "memory-db-maintenance":
            t.join(timeout=10)
    # Two sibling pieces of one over-long line: same triple, distinct ids.
    for i in (1, 2):
        s.save_chunk(MemoryChunk(
            id=f"long#{i}", user_id=None, scope="shared", source="memory",
            path="memory/shared/long.md", start_line=1, end_line=1,
            text=f"piece {i}", embedding=None, hash=f"h{i}",
        ))
    s.conn.commit()
    yield s
    s.close()


def test_a_hit_credits_only_the_matched_piece(storage):
    storage.record_hits([("long#2", "memory/shared/long.md", 1, 1)])

    stats = storage.get_hit_stats([
        ("long#1", "memory/shared/long.md", 1, 1),
        ("long#2", "memory/shared/long.md", 1, 1),
    ])

    assert stats[("long#1", "memory/shared/long.md", 1, 1)][0] == 0
    assert stats[("long#2", "memory/shared/long.md", 1, 1)][0] == 1
