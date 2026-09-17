import asyncio
import os
from pathlib import Path
from unittest.mock import patch

from agent.memory.storage import MemoryChunk, MemoryStorage
from agent.knowledge.service import KnowledgeService


class FakeStorage:
    def __init__(self):
        self.deleted = []

    def delete_by_path(self, path):
        self.deleted.append(path)


class FakeMemoryManager:
    def __init__(self):
        self.storage = FakeStorage()
        self.dirty = 0
        self.synced = 0

    def mark_dirty(self):
        self.dirty += 1

    async def sync(self):
        self.synced += 1


def service(tmp_path):
    (tmp_path / "knowledge").mkdir()
    manager = FakeMemoryManager()
    return KnowledgeService(str(tmp_path), manager), manager


def test_category_lifecycle_and_confirmation(tmp_path):
    svc, manager = service(tmp_path)
    assert svc.dispatch("create_category", {"path": "notes"})["payload"]["created"]
    (tmp_path / "knowledge/notes/a.md").write_text("# A", encoding="utf-8")

    denied = svc.dispatch("delete_category", {"path": "notes"})
    assert denied["code"] == 403

    result = svc.dispatch("delete_category", {"path": "notes", "confirm": True})
    assert result["payload"]["deleted_documents"] == 1
    assert manager.storage.deleted == ["knowledge/notes/a.md"]
    assert manager.synced == 1


def test_rename_category_reindexes_documents(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/old/sub").mkdir(parents=True)
    (tmp_path / "knowledge/old/a.md").write_text("a", encoding="utf-8")
    (tmp_path / "knowledge/old/sub/b.md").write_text("b", encoding="utf-8")

    result = svc.dispatch("rename_category", {"path": "old", "new_path": "new"})
    assert result["code"] == 200
    assert sorted(manager.storage.deleted) == [
        "knowledge/old/a.md", "knowledge/old/sub/b.md"
    ]
    assert manager.synced == 1
    assert (tmp_path / "knowledge/new/sub/b.md").exists()


def test_delete_documents_is_idempotent_and_protects_metadata(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/index.md").write_text("index", encoding="utf-8")
    (tmp_path / "knowledge/a.md").write_text("a", encoding="utf-8")

    protected = svc.dispatch("delete_documents", {"paths": ["index.md"]})
    assert protected["code"] == 403
    first = svc.dispatch("delete_documents", {"paths": ["a.md", "missing.md"]})
    assert first["payload"]["deleted"] == 1
    second = svc.dispatch("delete_documents", {"paths": ["a.md"]})
    assert second["payload"]["deleted"] == 0
    assert manager.storage.deleted == ["knowledge/a.md", "knowledge/missing.md", "knowledge/a.md"]
    assert manager.synced == 2


def test_move_documents_rejects_overwrite_and_syncs(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/source").mkdir()
    (tmp_path / "knowledge/target").mkdir()
    (tmp_path / "knowledge/source/a.md").write_text("a", encoding="utf-8")
    (tmp_path / "knowledge/source/b.md").write_text("b", encoding="utf-8")
    (tmp_path / "knowledge/target/b.md").write_text("existing", encoding="utf-8")

    result = svc.dispatch("move_documents", {
        "paths": ["source/a.md", "source/b.md"], "target_category": "target"
    })
    assert result["payload"]["moved"] == 1
    assert result["payload"]["results"][1]["reason"] == "target_exists"
    assert manager.storage.deleted == ["knowledge/source/a.md"]
    assert manager.synced == 1


def test_path_traversal_and_symlink_escape_are_rejected(tmp_path):
    svc, _ = service(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "knowledge/link").symlink_to(outside, target_is_directory=True)

    assert svc.dispatch("create_category", {"path": "../bad"})["code"] == 403
    assert svc.dispatch("create_category", {"path": "link/bad"})["code"] == 403


def test_dispatch_sync_works_inside_running_event_loop(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/source").mkdir()
    (tmp_path / "knowledge/target").mkdir()
    (tmp_path / "knowledge/source/a.md").write_text("a", encoding="utf-8")

    async def run():
        return svc.dispatch("move_documents", {
            "paths": ["source/a.md"], "target_category": "target"
        })

    assert asyncio.run(run())["code"] == 200
    assert manager.synced == 1


def test_real_storage_delete_by_path_removes_chunks_and_file_metadata(tmp_path):
    storage = MemoryStorage(tmp_path / "index.db")
    path = "knowledge/category/a.md"
    storage.save_chunks_batch([MemoryChunk(
        id="chunk-1", user_id=None, scope="shared", source="knowledge",
        path=path, start_line=1, end_line=1, text="unique content",
        embedding=None, hash="hash-1",
    )])
    storage.update_file_metadata(path, "knowledge", "file-hash", 1, 14)

    storage.delete_by_path(path)

    assert storage.conn.execute("SELECT COUNT(*) FROM chunks WHERE path = ?", (path,)).fetchone()[0] == 0
    assert storage.conn.execute("SELECT COUNT(*) FROM files WHERE path = ?", (path,)).fetchone()[0] == 0
    storage.close()


def test_missing_document_still_cleans_stale_index(tmp_path):
    svc, manager = service(tmp_path)

    result = svc.dispatch("delete_documents", {"paths": ["removed-by-agent.md"]})

    assert result["code"] == 200
    assert result["payload"]["results"][0]["reason"] == "not_found"
    assert manager.storage.deleted == ["knowledge/removed-by-agent.md"]
    assert manager.dirty == 1
    assert manager.synced == 1


def test_category_rename_handles_concurrent_disappearance(tmp_path):
    svc, manager = service(tmp_path)
    category = tmp_path / "knowledge/source"
    category.mkdir()
    (category / "a.md").write_text("a", encoding="utf-8")
    def disappear_then_rename(path, target):
        (category / "a.md").unlink()
        category.rmdir()
        raise FileNotFoundError(path)

    with patch.object(Path, "rename", disappear_then_rename):
        result = svc.dispatch("rename_category", {"path": "source", "new_path": "target"})

    assert result["code"] == 200
    assert result["payload"]["reason"] == "not_found"
    assert manager.storage.deleted == []


def test_category_delete_handles_concurrent_disappearance(tmp_path):
    svc, manager = service(tmp_path)
    category = tmp_path / "knowledge/source"
    category.mkdir()
    (category / "a.md").write_text("a", encoding="utf-8")

    def disappear_then_delete(path):
        (category / "a.md").unlink()
        category.rmdir()
        raise FileNotFoundError(path)

    with patch("agent.knowledge.service.shutil.rmtree", side_effect=disappear_then_delete):
        result = svc.dispatch("delete_category", {"path": "source", "confirm": True})

    assert result["code"] == 200
    assert result["payload"]["reason"] == "not_found"
    assert manager.storage.deleted == []


def test_move_does_not_overwrite_target_created_concurrently(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/source").mkdir()
    (tmp_path / "knowledge/target").mkdir()
    source = tmp_path / "knowledge/source/a.md"
    target = tmp_path / "knowledge/target/a.md"
    source.write_text("source", encoding="utf-8")
    real_link = os.link

    def create_target_then_link(src, dst):
        target.write_text("concurrent", encoding="utf-8")
        return real_link(src, dst)

    with patch("agent.knowledge.service.os.link", side_effect=create_target_then_link):
        result = svc.dispatch("move_documents", {
            "paths": ["source/a.md"], "target_category": "target",
        })

    assert result["payload"]["results"][0]["reason"] == "target_exists"
    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "concurrent"
    assert manager.storage.deleted == []


def test_create_document_writes_and_syncs(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/notes").mkdir()

    result = svc.dispatch("create_document", {
        "path": "notes/new.md", "content": "# New\nBody",
    })

    assert result["code"] == 200
    assert (tmp_path / "knowledge/notes/new.md").read_text(encoding="utf-8") == "# New\nBody"
    assert manager.dirty == 1
    assert manager.synced == 1


def test_import_documents_supports_md_txt_and_rename_conflicts(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/notes").mkdir()
    (tmp_path / "knowledge/notes/a.md").write_text("existing", encoding="utf-8")

    result = svc.dispatch("import_documents", {
        "target_category": "notes",
        "conflict_strategy": "rename",
        "files": [
            {"filename": "a.md", "content": b"# A"},
            {"filename": "plain.txt", "content": "plain text"},
        ],
    })

    assert result["code"] == 200
    assert result["payload"]["imported"] == 2
    assert (tmp_path / "knowledge/notes/a-1.md").read_text(encoding="utf-8") == "# A"
    assert (tmp_path / "knowledge/notes/plain.md").read_text(encoding="utf-8") == "plain text"
    assert manager.storage.deleted == []
    assert manager.synced == 1


def test_import_documents_skip_overwrite_and_failures(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/notes").mkdir()
    existing = tmp_path / "knowledge/notes/a.md"
    existing.write_text("old", encoding="utf-8")

    skipped = svc.dispatch("import_documents", {
        "target_category": "notes",
        "conflict_strategy": "skip",
        "files": [{"filename": "a.md", "content": b"new"}],
    })
    assert skipped["payload"]["skipped"] == 1
    assert existing.read_text(encoding="utf-8") == "old"
    assert manager.synced == 0

    overwritten = svc.dispatch("import_documents", {
        "target_category": "notes",
        "conflict_strategy": "overwrite",
        "files": [
            {"filename": "a.md", "content": b"new"},
            {"filename": "bad.pdf", "content": b"%PDF"},
        ],
    })
    assert overwritten["payload"]["imported"] == 1
    assert overwritten["payload"]["failed"] == 1
    assert existing.read_text(encoding="utf-8") == "new"
    assert manager.storage.deleted == ["knowledge/notes/a.md"]
    assert manager.synced == 1


def test_import_documents_rejects_large_files_and_batches(tmp_path):
    svc, manager = service(tmp_path)
    (tmp_path / "knowledge/notes").mkdir()
    assert svc.MAX_IMPORT_TOTAL_SIZE == 200 * 1024 * 1024

    too_large = svc.dispatch("import_documents", {
        "target_category": "notes",
        "files": [{"filename": "big.md", "content": b"x" * (svc.MAX_IMPORT_FILE_SIZE + 1)}],
    })
    assert too_large["payload"]["failed"] == 1
    assert too_large["payload"]["results"][0]["reason"] == "file too large"

    too_many = svc.dispatch("import_documents", {
        "target_category": "notes",
        "files": [{"filename": f"{i}.md", "content": b"x"} for i in range(svc.MAX_IMPORT_FILES + 1)],
    })
    assert too_many["code"] == 403
    assert "too many files" in too_many["message"]
    assert manager.synced == 0


def test_build_graph_resolves_encoded_and_anchored_links(tmp_path):
    svc, _ = service(tmp_path)
    root = tmp_path / "knowledge"
    (root / "concepts").mkdir()
    (root / "sources").mkdir()
    (root / "sources/训练记录 07.md").write_text("# 训练记录", encoding="utf-8")
    (root / "concepts/rag.md").write_text("# RAG", encoding="utf-8")
    (root / "concepts/health.md").write_text(
        "# Health\n"
        "- [记录](../sources/%E8%AE%AD%E7%BB%83%E8%AE%B0%E5%BD%95%2007.md)\n"
        "- [RAG](./rag.md#chunking)\n"
        "- [外部](https://example.com/a.md)\n",
        encoding="utf-8",
    )

    graph = svc.build_graph()
    edges = {(l["source"], l["target"]) for l in graph["links"]}
    assert ("concepts/health.md", "sources/训练记录 07.md") in edges
    assert ("concepts/health.md", "concepts/rag.md") in edges
    assert len(edges) == 2
