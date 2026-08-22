"""Factory for optional memory vector backends."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from agent.memory.config import MemoryConfig
from agent.memory.milvus_backend import MilvusVectorBackend
from agent.memory.vector_backend import VectorBackend


def create_external_vector_backend(
    config: MemoryConfig,
    dimension: Optional[int],
) -> Optional[VectorBackend]:
    """Create the configured external backend, or ``None`` for SQLite."""
    backend_name = (config.vector_backend or "sqlite").strip().lower()
    if backend_name == "sqlite":
        return None
    if backend_name != "milvus":
        raise ValueError("Unknown memory vector backend: {}".format(backend_name))
    if not dimension or dimension <= 1:
        # Memory is keyword-only until an embedding provider becomes available.
        return None

    workspace = os.path.realpath(str(config.get_workspace()))
    workspace_id = hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:16]
    collection = (config.milvus_collection or "").strip()
    if not collection:
        collection = "cowagent_memory_{}_d{}".format(workspace_id, dimension)

    uri = (config.milvus_uri or "").strip()
    if not uri:
        uri = str(
            Path(config.get_db_path()).with_name("milvus.db").resolve()
        )

    token = os.environ.get("MILVUS_TOKEN") or config.milvus_token or ""
    return MilvusVectorBackend(
        uri=uri,
        collection_name=collection,
        dimension=dimension,
        workspace_id=workspace_id,
        token=token,
        db_name=config.milvus_db_name,
        timeout=config.milvus_timeout,
        consistency_level=config.milvus_consistency_level,
    )
