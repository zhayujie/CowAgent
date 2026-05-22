"""
Rebuild memory vector index.

Recommended entry point (in-chat, while agent is running):
    /memory rebuild-index

Backward-compatible CLI entry (must run from project root):
    python -m agent.memory.rebuild_index

What it does:
  1. Probes the embedding endpoint with a tiny call to fail fast on
     bad provider/model/key — before touching the index.
  2. Clears the SQLite chunks/files tables (workspace markdown stays intact).
  3. Runs a fresh sync, regenerating embeddings with the currently configured
     provider/model/dimensions.

This is the only safe way to switch embedding_provider after the existing
index has been populated by a different-dim model.
"""

from __future__ import annotations
import asyncio
import sys
from dataclasses import dataclass
from typing import Optional

from common.log import logger
from common.utils import expand_path


@dataclass
class RebuildResult:
    """Outcome of a rebuild_in_process() call"""
    ok: bool
    removed: int = 0
    chunks: int = 0
    files: int = 0
    error: Optional[str] = None


def clear_index(db_path, storage=None) -> int:
    """Wipe chunks/files, reset FTS5, and clean up any legacy state file.

    Args:
        db_path: Path of the index DB (also used to locate the legacy state
            file for migration cleanup, and — when *storage* is None — to
            open a fresh connection).
        storage: Optional pre-opened MemoryStorage. When provided we reuse it
            so the live connection's triggers stay in sync — opening a second
            connection would leave the original one's triggers pointing at a
            DROP'd chunks_fts table.

    We reset (DROP+recreate) chunks_fts because its shadow tables can become
    inconsistent across rebuild cycles, causing bm25() / ORDER BY rank to
    raise "database disk image is malformed" even when raw MATCH still works.

    Returns number of chunks removed.
    """
    from agent.memory.embedding.state import cleanup_legacy_state_file
    from agent.memory.storage import MemoryStorage

    owns_storage = storage is None
    if owns_storage:
        storage = MemoryStorage(db_path)
    try:
        before = storage.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        storage.conn.execute("DELETE FROM chunks")
        storage.conn.execute("DELETE FROM files")
        storage.conn.commit()
        storage.reset_fts5()
    finally:
        if owns_storage:
            storage.close()

    cleanup_legacy_state_file(db_path)
    return int(before)


def rebuild_in_process(memory_manager) -> RebuildResult:
    """
    Rebuild the index using an existing, fully-initialized MemoryManager.

    Used by the in-chat /memory rebuild-index command. The caller already has
    config loaded, embedding_provider built, and (optionally) the agent
    running, so we only need to:
      1. Clear chunks/files + state on the manager's storage.
      2. Re-sync (force=True).

    NOTE: caller must ensure memory_manager.embedding_provider is set, otherwise
    sync() will silently skip embedding generation.
    """
    if memory_manager is None:
        return RebuildResult(ok=False, error="memory_manager is None")
    if memory_manager.embedding_provider is None:
        return RebuildResult(ok=False, error="embedding_provider is not initialized")

    # Probe the embedding endpoint BEFORE clearing the index. A bad
    # provider/model/key would otherwise leave the user with an empty index
    # that not even keyword search can serve.
    try:
        memory_manager.embedding_provider.embed_query("ping")
    except Exception as e:
        logger.error(f"[RebuildIndex] embedding probe failed, aborting rebuild: {e}")
        return RebuildResult(ok=False, error=f"embedding endpoint not reachable: {e}")

    db_path = memory_manager.config.get_db_path()
    try:
        removed = clear_index(db_path, storage=memory_manager.storage)
    except Exception as e:
        logger.exception("[RebuildIndex] clear_index failed")
        return RebuildResult(ok=False, error=f"clear failed: {e}")

    try:
        asyncio.run(memory_manager.sync(force=True))
    except RuntimeError:
        # Already inside a running event loop (rare in chat handler thread).
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(memory_manager.sync(force=True))
        finally:
            loop.close()
    except Exception as e:
        logger.exception("[RebuildIndex] sync failed")
        return RebuildResult(ok=False, removed=removed, error=f"re-embed failed: {e}")

    stats = memory_manager.storage.get_stats()
    chunks = int(stats.get("chunks", 0))
    embedded = int(stats.get("embedded", 0))

    # sync() degrades to "no embeddings" on batch failure so keyword search
    # still works at startup — but in a /rebuild-index request the user
    # explicitly asked for vectors. Surface that as a failure.
    if chunks > 0 and embedded == 0:
        return RebuildResult(
            ok=False,
            removed=removed,
            chunks=chunks,
            files=int(stats.get("files", 0)),
            error=(
                "embedding API failed during sync; index now has chunks but no "
                "vectors. Check embedding provider/model/key and retry."
            ),
        )

    return RebuildResult(
        ok=True,
        removed=removed,
        chunks=chunks,
        files=int(stats.get("files", 0)),
    )


def main() -> int:
    """Standalone CLI entry. Must be run from project root (relative config path)."""
    from config import conf, load_config
    from agent.memory import MemoryConfig, MemoryManager

    load_config()

    workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
    memory_config = MemoryConfig(workspace_root=workspace_root)

    logger.info(f"[RebuildIndex] Workspace: {workspace_root}")
    logger.info(f"[RebuildIndex] Index db:  {memory_config.get_db_path()}")

    from bridge.agent_initializer import AgentInitializer

    initializer = AgentInitializer(bridge=None, agent_bridge=None)
    embedding_provider = initializer._init_embedding_provider(memory_config, session_id=None)
    if embedding_provider is None:
        logger.error(
            "[RebuildIndex] No embedding provider could be initialized. "
            "Check your config.json. Aborting rebuild."
        )
        return 1

    manager = MemoryManager(memory_config, embedding_provider=embedding_provider)
    result = rebuild_in_process(manager)
    if not result.ok:
        logger.error(f"[RebuildIndex] {result.error}")
        return 1

    logger.info(
        f"[RebuildIndex] Done. removed={result.removed}, "
        f"chunks={result.chunks}, files={result.files}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
