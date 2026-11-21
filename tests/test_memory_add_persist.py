# encoding:utf-8
"""add_memory() must persist its backing file so sync() keeps its indexed rows."""

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager


def _manager(workspace: Path, embedding_provider=None) -> MemoryManager:
    return MemoryManager(
        config=MemoryConfig(workspace_root=str(workspace)),
        embedding_provider=embedding_provider,
    )


class _CountingEmbeddingProvider:
    model = "stub-embed"

    def __init__(self):
        self.batch_calls = 0

    def embed_batch(self, texts):
        self.batch_calls += 1
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, query):
        return [1.0, 0.0, 0.0]


@pytest.fixture(autouse=True)
def _isolated_shared_root(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    (shared / "knowledge").mkdir(parents=True)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)


def test_add_memory_auto_path_persists_file_and_survives_sync(tmp_path):
    workspace = tmp_path / "workspace"
    manager = _manager(workspace)
    content = "Remember token VELVETCOMPASS8821 for deployment.\n"
    expected_rel = f"memory/shared/memory_{hashlib.md5(content.encode('utf-8')).hexdigest()[:8]}.md"

    asyncio.run(manager.add_memory(content))

    persisted = workspace / expected_rel
    assert persisted.is_file()
    assert persisted.read_text(encoding="utf-8") == content

    row = manager.storage.conn.execute(
        "SELECT mtime, size FROM files WHERE path = ?", (expected_rel,)
    ).fetchone()
    stat = persisted.stat()
    assert row["mtime"] == int(stat.st_mtime)
    assert row["size"] == stat.st_size

    asyncio.run(manager.sync())

    assert expected_rel in manager.storage.list_paths("memory")
    results = asyncio.run(manager.search("VELVETCOMPASS8821", min_score=0.0))
    assert any(r.path == expected_rel for r in results)


def test_add_memory_user_scope_creates_parents_and_survives_sync(tmp_path):
    workspace = tmp_path / "workspace"
    manager = _manager(workspace)
    content = "User note COBALTANCHOR5519 for u1.\n"
    rel_path = f"memory/users/u1/memory_{hashlib.md5(content.encode('utf-8')).hexdigest()[:8]}.md"

    asyncio.run(manager.add_memory(content, user_id="u1", scope="user"))

    persisted = workspace / rel_path
    assert persisted.is_file()
    assert persisted.read_text(encoding="utf-8") == content

    asyncio.run(manager.sync())

    assert rel_path in manager.storage.list_paths("memory")
    results = asyncio.run(manager.search("COBALTANCHOR5519", user_id="u1", min_score=0.0))
    assert any(r.path == rel_path for r in results)


def test_add_memory_leaves_the_file_at_an_explicit_path_alone(tmp_path):
    # The caller owns an explicit path: writing the snippet there would replace
    # whatever the file already holds, e.g. the whole of MEMORY.md.
    workspace = tmp_path / "workspace"
    manager = _manager(workspace)
    memory_md = workspace / "MEMORY.md"
    memory_md.parent.mkdir(parents=True, exist_ok=True)
    original = "# Memory\n\nLong-standing note SAFFRONBRIDGE6610.\n"
    memory_md.write_text(original, encoding="utf-8")

    asyncio.run(manager.add_memory("A snippet indexed under MEMORY.md.\n", path="MEMORY.md"))
    asyncio.run(manager.add_memory("Nothing on disk yet.\n", path="memory/shared/absent.md"))

    assert memory_md.read_text(encoding="utf-8") == original
    assert not (workspace / "memory/shared/absent.md").exists()


def test_add_memory_is_up_to_date_on_next_sync_without_reembedding(tmp_path):
    workspace = tmp_path / "workspace"
    provider = _CountingEmbeddingProvider()
    manager = _manager(workspace, embedding_provider=provider)
    content = "Cached embedding check AMBERLANTERN3304.\n"

    asyncio.run(manager.add_memory(content))
    assert provider.batch_calls == 1

    asyncio.run(manager.sync())
    assert provider.batch_calls == 1


def test_add_memory_does_not_rewrite_identical_existing_file(tmp_path):
    workspace = tmp_path / "workspace"
    manager = _manager(workspace)
    content = "Already written QUARTZHARBOR7742.\n"
    rel_path = f"memory/shared/memory_{hashlib.md5(content.encode('utf-8')).hexdigest()[:8]}.md"
    existing = workspace / rel_path
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(content, encoding="utf-8")
    fixed_mtime = 1700000000
    os.utime(existing, (fixed_mtime, fixed_mtime))

    asyncio.run(manager.add_memory(content))

    assert int(existing.stat().st_mtime) == fixed_mtime
    asyncio.run(manager.sync())
    assert rel_path in manager.storage.list_paths("memory")


def test_add_memory_rejects_path_traversal(tmp_path):
    workspace = tmp_path / "workspace"
    manager = _manager(workspace)
    outside = tmp_path / "escape.md"

    with pytest.raises(ValueError):
        asyncio.run(manager.add_memory("escape attempt", path="../escape.md"))
    with pytest.raises(ValueError):
        asyncio.run(manager.add_memory("escape attempt", path=str(outside)))

    assert not outside.exists()
    assert manager.storage.list_paths("memory") == []
