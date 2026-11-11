"""A category must not be named after a protected knowledge file.

``index.md`` and ``log.md`` are generated/maintained by the service. Allowing a
category (a directory) with one of those names shadows the real file, after
which ``rebuild_index_md`` raises ``IsADirectoryError`` and is silently
swallowed -- the directory listing then stops updating.
"""

import pytest

from agent.knowledge.service import KnowledgeService


class FakeStorage:
    def delete_by_path(self, path):
        pass


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
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)
    return KnowledgeService(str(tmp_path), FakeMemoryManager())


def test_create_category_rejects_protected_name(tmp_path):
    svc = service(tmp_path)
    for name in ("index.md", "log.md", "notes/index.md"):
        with pytest.raises(ValueError):
            svc.create_category(name)


def test_create_category_allows_normal_name(tmp_path):
    svc = service(tmp_path)
    assert svc.create_category("notes") == {"path": "notes", "created": True}


def test_rename_category_rejects_protected_name(tmp_path):
    svc = service(tmp_path)
    svc.create_category("notes")
    with pytest.raises(ValueError):
        svc.rename_category("notes", "index.md")
