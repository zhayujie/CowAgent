"""
Embedding subsystem for memory.

Public API:
  create_embedding_provider, EmbeddingProvider, OpenAIEmbeddingProvider,
  EMBEDDING_VENDORS, EmbeddingCache
  RebuildResult, clear_index, rebuild_in_process
  detect_index_dim, cleanup_legacy_state_file
"""

from agent.memory.embedding.provider import (
    EMBEDDING_VENDORS,
    DoubaoEmbeddingProvider,
    EmbeddingCache,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embedding_provider,
)
from agent.memory.embedding.rebuild import (
    RebuildResult,
    clear_index,
    rebuild_in_process,
)
from agent.memory.embedding.state import (
    cleanup_legacy_state_file,
    detect_index_dim,
)

__all__ = [
    "EMBEDDING_VENDORS",
    "DoubaoEmbeddingProvider",
    "EmbeddingCache",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "create_embedding_provider",
    "RebuildResult",
    "clear_index",
    "rebuild_in_process",
    "cleanup_legacy_state_file",
    "detect_index_dim",
]
