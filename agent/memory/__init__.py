"""
Memory module for AgentMesh

Provides both long-term memory (vector/keyword search) and short-term
conversation history persistence (SQLite).
"""

from agent.memory.config import (
    MemoryConfig,
    get_default_memory_config,
    register_memory_config,
    reset_memory_configs,
    set_global_memory_config,
)
from agent.memory.conversation_store import (
    ConversationStore,
    clear_conversation_store_cache,
    get_conversation_store,
    migrate_conversations_to_global,
)
from agent.memory.embedding import (
    create_default_embedding_provider,
    create_embedding_provider,
)
from agent.memory.manager import MemoryManager
from agent.memory.reranker import (
    DEFAULT_RERANK_MODEL,
    Reranker,
    SentenceTransformerReranker,
    create_reranker,
)
from agent.memory.summarizer import ensure_daily_memory_file
from agent.memory.vector_backend import (
    SQLiteVectorBackend,
    VectorBackend,
    VectorMatch,
    VectorRecord,
)

__all__ = [
    'MemoryManager',
    'MemoryConfig',
    'get_default_memory_config',
    'register_memory_config',
    'reset_memory_configs',
    'set_global_memory_config',
    'create_embedding_provider',
    'create_default_embedding_provider',
    'Reranker',
    'SentenceTransformerReranker',
    'create_reranker',
    'DEFAULT_RERANK_MODEL',
    'VectorBackend',
    'SQLiteVectorBackend',
    'VectorRecord',
    'VectorMatch',
    'ConversationStore',
    'clear_conversation_store_cache',
    'get_conversation_store',
    'migrate_conversations_to_global',
    'ensure_daily_memory_file',
]
