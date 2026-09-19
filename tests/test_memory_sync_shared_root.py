# encoding:utf-8
"""sync() must survive scan targets that live outside the workspace.

``common.state_dir._shared_or_own`` sends an Agent that has no local
``knowledge/`` of its own to the SHARED root, so sync() legitimately scans
files that are not under the workspace. Indexing them called
``file_path.relative_to(workspace_dir)``, which raises ValueError for those
paths; the call sat inside the scan loop, so one such file aborted the whole
sync — and every retrieval routed through the ``search()`` in front of it
(#3175).

A shared file must also keep the same index key it would have had inside the
workspace — ``knowledge/note.md``, not an absolute path.
"""

import asyncio
from pathlib import Path

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager


def test_sync_indexes_shared_knowledge_outside_the_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # A shared root outside the workspace, the way _shared_or_own resolves it
    # for an Agent whose workspace has no knowledge/ of its own.
    shared = tmp_path / "shared"
    (shared / "knowledge").mkdir(parents=True)
    (shared / "knowledge" / "note.md").write_text(
        "# note\nGLACIERQUARTZ7731\n", encoding="utf-8"
    )

    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(workspace)))
    manager._init_workspace()

    asyncio.run(manager.sync())

    assert manager.storage.get_file_hash("knowledge/note.md") is not None
