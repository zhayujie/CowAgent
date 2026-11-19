# encoding:utf-8
"""A CJK query run must not be matched as one exact substring.

Chinese queries arrive unsegmented — a natural-language query is a single
long run. Quoting that run as one FTS5 phrase (and one LIKE pattern)
demanded the exact contiguous substring, so 「怎么配置微信机器人」 returned
*nothing* for a memory phrased 「如何配置微信机器人」 even though the two
share most of their trigrams; in keyword-only installs memory_search came
back "No memories found". Runs of 4+ characters are now split into
overlapping 3-character shingles (OR within a run, AND across tokens);
BM25 / the matched-word score keep precision through ranking.
"""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.storage import MemoryChunk, MemoryStorage


@pytest.fixture
def storage(tmp_path):
    s = MemoryStorage(tmp_path / "index.db")
    for t in threading.enumerate():
        if t.name == "memory-db-maintenance":
            t.join(timeout=10)
    s.save_chunk(MemoryChunk(
        id="c1", user_id=None, scope="shared", source="memory",
        path="memory/shared/wechat.md", start_line=1, end_line=1,
        text="用户询问如何配置微信机器人，已指引完成扫码登录。", embedding=None, hash="h1",
    ))
    s.conn.commit()
    yield s
    s.close()


def test_a_reworded_cjk_query_finds_the_memory(storage):
    """The query shares most — not all — characters with the stored phrasing."""
    results = storage.search_keyword("怎么配置微信机器人")

    assert [r.path for r in results] == ["memory/shared/wechat.md"]


def test_a_reworded_cjk_query_finds_the_memory_in_the_like_fallback(storage):
    storage.trigram_fts5_available = False

    results = storage._search_like("怎么配置微信机器人", None, ["shared"], 20)

    assert [r.path for r in results] == ["memory/shared/wechat.md"]


def test_an_exact_phrase_match_still_outranks_a_partial_one(tmp_path):
    s = MemoryStorage(tmp_path / "index.db")
    for t in threading.enumerate():
        if t.name == "memory-db-maintenance":
            t.join(timeout=10)
    s.save_chunk(MemoryChunk(
        id="exact", user_id=None, scope="shared", source="memory",
        path="memory/shared/exact.md", start_line=1, end_line=1,
        text="怎么配置微信机器人：三步完成。", embedding=None, hash="hx",
    ))
    s.save_chunk(MemoryChunk(
        id="partial", user_id=None, scope="shared", source="memory",
        path="memory/shared/partial.md", start_line=1, end_line=1,
        text="机器人打扫了房间。", embedding=None, hash="hp",
    ))
    s.conn.commit()

    results = s.search_keyword("怎么配置微信机器人")

    assert results, "nothing matched"
    assert results[0].path == "memory/shared/exact.md", (
        "the exact phrasing must outrank a single-shingle overlap"
    )
    s.close()


def test_short_cjk_runs_keep_exact_matching(storage):
    # A 3-character query is its own trigram: unchanged semantics.
    assert MemoryStorage._build_trigram_query("机器人") == '"机器人"'
    results = storage.search_keyword("机器人")

    assert [r.path for r in results] == ["memory/shared/wechat.md"]
