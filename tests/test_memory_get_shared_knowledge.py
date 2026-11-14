# encoding:utf-8
"""memory_get must be able to open the keys memory_search hands back.

sync() indexes shared knowledge under "knowledge/<rel>" (#3175), but memory_get
resolved that key under the Agent's own workspace. An Agent with no private
knowledge/ of its own was therefore told about pages it could not then read, and
burned turns guessing at nearby paths instead of answering.
"""

import types
from pathlib import Path

import pytest

from agent.tools.memory.memory_get import MemoryGetTool


def _tool(workspace):
    """The tool only ever asks the manager for its workspace."""
    config = types.SimpleNamespace(get_workspace=lambda: Path(workspace))
    return MemoryGetTool(types.SimpleNamespace(config=config))


def _layout(tmp_path):
    workspace = tmp_path / "agents" / "pm"
    workspace.mkdir(parents=True)
    shared = tmp_path / "shared"
    (shared / "knowledge" / "entities").mkdir(parents=True)
    return workspace, shared


def test_reads_shared_knowledge_when_the_agent_has_no_copy(tmp_path, monkeypatch):
    workspace, shared = _layout(tmp_path)
    (shared / "knowledge" / "entities" / "linkai.md").write_text(
        "# LinkAI\nVELVETCOMPASS8815\n", encoding="utf-8"
    )
    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)

    result = _tool(workspace).execute({"path": "knowledge/entities/linkai.md"})

    assert result.status == "success"
    assert "VELVETCOMPASS8815" in result.result


def test_a_private_copy_still_wins_over_the_shared_one(tmp_path, monkeypatch):
    workspace, shared = _layout(tmp_path)
    (shared / "knowledge" / "entities" / "linkai.md").write_text("shared\n", encoding="utf-8")
    (workspace / "knowledge" / "entities").mkdir(parents=True)
    (workspace / "knowledge" / "entities" / "linkai.md").write_text(
        "# LinkAI\nOWNCOPY2290\n", encoding="utf-8"
    )
    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)

    result = _tool(workspace).execute({"path": "knowledge/entities/linkai.md"})

    assert result.status == "success"
    assert "OWNCOPY2290" in result.result


def test_traversal_out_of_the_knowledge_root_is_still_denied(tmp_path, monkeypatch):
    workspace, shared = _layout(tmp_path)
    (tmp_path / "secret.md").write_text("NOTFORAGENTS\n", encoding="utf-8")
    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)

    result = _tool(workspace).execute({"path": "knowledge/../../secret.md"})

    assert result.status == "error"
    assert "Access denied" in result.result


def test_scoped_knowledge_get_cannot_reach_root_memory(tmp_path, monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "knowledge", True)
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "MEMORY.md").write_text("owner memory", encoding="utf-8")
    tool = _tool(tmp_path)
    tool.allowed_memory_scope = "feishu-group-test"

    result = tool.execute({"path": "knowledge/../MEMORY.md"})
    assert result.status == "error"
    assert "Access denied" in result.result


def test_scoped_search_drops_previously_indexed_knowledge_link(tmp_path, monkeypatch):
    import asyncio
    from agent.memory.config import MemoryConfig
    from agent.memory.manager import MemoryManager
    from agent.memory.storage import MemoryChunk
    from config import conf

    monkeypatch.setitem(conf(), "knowledge", True)
    (tmp_path / "knowledge").mkdir()
    private = tmp_path / "MEMORY.md"
    private.write_text("ownersecret", encoding="utf-8")
    link = tmp_path / "knowledge" / "linked.md"
    try:
        link.symlink_to(private)
    except OSError as exc:
        pytest.skip(f"File symlinks unavailable: {exc}")

    manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path)))
    try:
        manager.storage.save_chunk(MemoryChunk(
            id="old-chunk", user_id=None, scope="shared", source="knowledge",
            path="knowledge/linked.md", start_line=1, end_line=1,
            text="ownersecret", embedding=None, hash="old-hash",
        ))
        manager.storage.update_file_metadata("knowledge/linked.md", "knowledge", "old-hash", 0, 11)
        assert manager.storage.search_keyword("ownersecret")
        results = asyncio.run(manager.search(
            "ownersecret", user_id="feishu-group-test", include_shared=False, include_knowledge=True,
        ))
        assert results == []

        tool = MemoryGetTool(manager)
        tool.allowed_memory_scope = "feishu-group-test"
        assert tool.execute({"path": "knowledge/linked.md"}).status == "error"

        asyncio.run(manager.sync())
        assert "knowledge/linked.md" not in manager.storage.list_paths("knowledge")
        assert manager.storage.get_chunk("old-chunk") is None
    finally:
        manager.close()


def test_memory_paths_are_untouched(tmp_path, monkeypatch):
    workspace, shared = _layout(tmp_path)
    (workspace / "memory").mkdir()
    (workspace / "memory" / "2026-01-01.md").write_text("# day\nDAILYNOTE771\n", encoding="utf-8")
    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)

    result = _tool(workspace).execute({"path": "memory/2026-01-01.md"})

    assert result.status == "success"
    assert "DAILYNOTE771" in result.result
