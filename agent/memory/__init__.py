"""
Memory module for AgentMesh

Provides both long-term memory (vector/keyword search) and short-term
conversation history persistence (SQLite).
"""

from agent.memory.config import (
    MemoryConfig,
    create_memory_config,
    get_default_memory_config,
    register_memory_config,
    reset_memory_configs,
    set_global_memory_config,
)
from agent.memory.conversation_store import (
    ConversationStore,
    clear_conversation_store_cache,
    get_conversation_store,
)
from agent.memory.embedding import (
    create_default_embedding_provider,
    create_embedding_provider,
)
from agent.memory.manager import MemoryManager
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
    'create_memory_config',
    'get_default_memory_config',
    'register_memory_config',
    'reset_memory_configs',
    'set_global_memory_config',
    'create_embedding_provider',
    'create_default_embedding_provider',
    'VectorBackend',
    'SQLiteVectorBackend',
    'VectorRecord',
    'VectorMatch',
    'ConversationStore',
    'clear_conversation_store_cache',
    'get_conversation_store',
    'ensure_daily_memory_file',
]
