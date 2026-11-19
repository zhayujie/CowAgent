"""A category name must not end in ``.md``.

``rebuild_index_md`` collects every ``*.md`` path as a document, so a category
directory named like one (``foo.md``, ``index.md``, ``log.md``) would be listed
as a document.
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
    for name in ("index.md", "log.md", "notes/index.md", "foo.md", "Notes.MD", "a.md/b"):
        with pytest.raises(ValueError):
            svc.create_category(name)


def test_create_category_allows_normal_name(tmp_path):
    svc = service(tmp_path)
    assert svc.create_category("notes") == {"path": "notes", "created": True}


def test_rename_category_rejects_protected_name(tmp_path):
    svc = service(tmp_path)
    svc.create_category("notes")
    for name in ("index.md", "foo.md", "sub.MD/x"):
        with pytest.raises(ValueError):
            svc.rename_category("notes", name)


def test_a_name_merely_containing_md_is_allowed(tmp_path):
    svc = service(tmp_path)
    assert svc.create_category("md-notes")["created"] is True
    assert svc.create_category("notes.mdx")["created"] is True
