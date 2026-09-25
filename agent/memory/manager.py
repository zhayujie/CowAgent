"""
Memory manager for AgentMesh

Provides high-level interface for memory operations
"""

import os
from typing import List, Optional, Dict, Any, Sequence, Tuple
from pathlib import Path
import hashlib
from datetime import datetime

from agent.memory.config import MemoryConfig, get_default_memory_config
from agent.memory.storage import MemoryStorage, MemoryChunk, SearchResult
from agent.memory.chunker import TextChunker
from agent.memory.embedding import EmbeddingProvider, EmbeddingCache
from agent.memory.reranker import Reranker
from agent.memory.summarizer import MemoryFlushManager, create_memory_files_if_needed


def _real(path: Path) -> Path:
    """Symlink-resolved path, for prefix comparisons that must not care how a
    directory was reached (``/var`` vs ``/private/var`` on macOS)."""
    try:
        return Path(os.path.realpath(path))
    except OSError:
        return Path(path)


def _index_rel_path(file_path: Path, roots: Sequence[Tuple[Path, str]]) -> Optional[str]:
    """Index key for a scanned file, or None when no known root contains it.

    Scanned files do not all come from one root: ``common.state_dir`` sends an
    Agent that has no local ``knowledge/`` of its own to the SHARED root, so
    sync() legitimately walks files outside the workspace. Keying those off the
    workspace alone raises ValueError, and because that ran inside sync()'s file
    loop a single such file aborted the whole sync — taking down every retrieval
    that goes through the ``search()`` in front of it (#3175).

    Each root carries the prefix its files are keyed under, so shared knowledge
    keeps the ``knowledge/note.md`` key it would have had inside the workspace:
    the index keeps its shape when an Agent gains or loses a private copy, and
    nothing has to be reindexed. Keys are POSIX-style on every platform, which
    is also the spelling ``add_memory`` writes — otherwise the same file is
    indexed twice on Windows, once per separator.

    Roots are matched as given first and only then symlink-resolved, so the
    common case costs no extra stat calls while a workspace reached through a
    symlink still matches instead of losing its files to the skip path.
    """
    for resolve in (False, True):
        target = _real(file_path) if resolve else file_path
        for root, prefix in roots:
            base = _real(root) if resolve else root
            try:
                rel = target.relative_to(base)
            except ValueError:
                continue
            return (Path(prefix) / rel).as_posix() if prefix else rel.as_posix()
    return None


class MemoryManager:
    """
    Memory manager with hybrid search capabilities
    
    Provides long-term memory for agents with vector and keyword search
    """
    
    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        llm_model: Optional[Any] = None,
        reranker: Optional[Reranker] = None
    ):
        """
        Initialize memory manager

        Args:
            config: Memory configuration (uses global config if not provided)
            embedding_provider: Custom embedding provider (optional)
            llm_model: LLM model for summarization (optional)
            reranker: Cross-encoder reranker for precision reordering (optional)
        """
        self.config = config or get_default_memory_config()
        
        # Initialize storage
        db_path = self.config.get_db_path()
        self.storage = MemoryStorage(db_path)
        
        # Initialize chunker
        self.chunker = TextChunker(
            max_tokens=self.config.chunk_max_tokens,
            overlap_tokens=self.config.chunk_overlap_tokens
        )
        
        # Embedding provider is owned by the caller (agent_initializer is the
        # canonical entry point and handles legacy/explicit + state validation).
        # When None is passed, memory degrades to keyword-only search instead
        # of silently re-initializing a vendor here, which would bypass the
        # caller's state checks and risk corrupting the index.
        self.embedding_provider = embedding_provider
        if self.embedding_provider is None:
            from common.log import logger
            logger.info(
                "[MemoryManager] No embedding provider; memory will use keyword search only"
            )

        # Cache for query embeddings (avoids redundant API calls within a session)
        self._embedding_cache = EmbeddingCache()

        # Optional cross-encoder reranker; None means un-reranked retrieval
        self.reranker = reranker

        # Initialize memory flush manager
        workspace_dir = self.config.get_workspace()
        self.flush_manager = MemoryFlushManager(
            workspace_dir=workspace_dir,
            llm_model=llm_model
        )
        
        # Ensure workspace directories exist
        self._init_workspace()
        
        self._dirty = False
    
    def _init_workspace(self):
        """Initialize workspace directories"""
        memory_dir = self.config.get_memory_dir()
        memory_dir.mkdir(parents=True, exist_ok=True)
        
        # Create default memory files
        workspace_dir = self.config.get_workspace()
        create_memory_files_if_needed(workspace_dir)
    
    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        max_results: Optional[int] = None,
        min_score: Optional[float] = None,
        include_shared: bool = True
    ) -> List[SearchResult]:
        """
        Search memory with hybrid search (vector + keyword)
        
        Args:
            query: Search query
            user_id: User ID for scoped search
            max_results: Maximum results to return
            min_score: Minimum score threshold
            include_shared: Include shared memories
            
        Returns:
            List of search results sorted by relevance
        """
        max_results = max_results or self.config.max_results
        min_score = min_score or self.config.min_score
        
        # Determine scopes
        scopes = []
        if include_shared:
            scopes.append("shared")
        if user_id:
            scopes.append("user")
        
        if not scopes:
            return []
        
        # Sync if needed
        if self.config.sync_on_search and self._dirty:
            await self.sync()
        
        from common.log import logger

        # Perform vector search (if embedding provider available).
        # Failures degrade silently to keyword-only — no exception is raised.
        vector_results = []
        if self.embedding_provider:
            try:
                provider_name = type(self.embedding_provider).__name__
                model_name = getattr(self.embedding_provider, 'model', '')
                cached = self._embedding_cache.get(query, provider_name, model_name)
                if cached is not None:
                    query_embedding = cached
                else:
                    query_embedding = self.embedding_provider.embed_query(query)
                    self._embedding_cache.put(query, provider_name, model_name, query_embedding)
                vector_results = self.storage.search_vector(
                    query_embedding=query_embedding,
                    user_id=user_id,
                    scopes=scopes,
                    limit=max_results * 2  # Get more candidates for merging
                )
                logger.info(f"[MemoryManager] Vector search found {len(vector_results)} results for query: {query}")
            except Exception as e:
                logger.error(
                    f"[MemoryManager] Vector search failed, falling back to keyword-only: {e}"
                )

        # Perform keyword search (also runs as fallback when vector failed)
        keyword_results = self.storage.search_keyword(
            query=query,
            user_id=user_id,
            scopes=scopes,
            limit=max_results * 2
        )
        logger.info(f"[MemoryManager] Keyword search found {len(keyword_results)} results for query: {query}")

        # Merge results
        merged = self._merge_results(
            vector_results,
            keyword_results,
            self.config.vector_weight,
            self.config.keyword_weight
        )

        # Precision-reorder with cross-encoder (no-op when no reranker configured)
        merged = self._rerank(query, merged)

        # Filter by min score and limit
        filtered = [r for r in merged if r.score >= min_score]
        return filtered[:max_results]
    
    async def add_memory(
        self,
        content: str,
        user_id: Optional[str] = None,
        scope: str = "shared",
        source: str = "memory",
        path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add new memory content
        
        Args:
            content: Memory content
            user_id: User ID for user-scoped memory
            scope: Memory scope ("shared", "user", "session")
            source: Memory source ("memory" or "session")
            path: File path (auto-generated if not provided)
            metadata: Additional metadata
        """
        if not content.strip():
            return
        
        # Generate path if not provided
        if not path:
            content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
            if user_id and scope == "user":
                path = f"memory/users/{user_id}/memory_{content_hash}.md"
            else:
                path = f"memory/shared/memory_{content_hash}.md"
        
        # Chunk content
        chunks = self.chunker.chunk_text(content)
        
        # Generate embeddings (if provider available)
        texts = [chunk.text for chunk in chunks]
        if self.embedding_provider:
            embeddings = self.embedding_provider.embed_batch(texts)
        else:
            # No embeddings, just use None
            embeddings = [None] * len(texts)
        
        # Create memory chunks
        memory_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = self._generate_chunk_id(path, chunk.start_line, chunk.end_line)
            chunk_hash = MemoryStorage.compute_hash(chunk.text)
            
            memory_chunks.append(MemoryChunk(
                id=chunk_id,
                user_id=user_id,
                scope=scope,
                source=source,
                path=path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text,
                embedding=embedding,
                hash=chunk_hash,
                metadata=metadata
            ))
        
        # Save to storage
        self.storage.save_chunks_batch(memory_chunks)
        
        # Update file metadata
        file_hash = MemoryStorage.compute_hash(content)
        self.storage.update_file_metadata(
            path=path,
            source=source,
            file_hash=file_hash,
            mtime=int(os.path.getmtime(__file__)),  # Use current time
            size=len(content)
        )
    
    async def sync(self, force: bool = False):
        """
        Synchronize memory from files.

        Two-pass design to amortize embedding HTTP cost:
          1. Walk all files, chunk those whose hash changed, collect pending
             chunks across files. No embedding calls yet.
          2. Run a single embed_batch over the union of pending chunks (the
             provider auto-paginates by vendor cap), then persist per-file.

        For workspaces with many small files (101 files / ~1 chunk each), this
        cuts ~100 HTTP calls down to ~ceil(total_chunks / vendor_cap).

        Args:
            force: Force full reindex
        """
        memory_dir = self.config.get_memory_dir()
        workspace_dir = self.config.get_workspace()

        # Was the index empty before this sync? Only then can we be sure every
        # chunk came from the CURRENT chunking algorithm (a fresh index, or one
        # cleared by rebuild-index), which is what lets us stamp
        # chunker_version. A non-empty index may still hold chunks from an
        # older algorithm, so it must not be stamped.
        try:
            files_before = int(self.storage.get_stats().get("files", 0) or 0)
        except Exception:
            files_before = -1  # unknown -> do not stamp

        files_to_scan: List[tuple] = []  # (file_path, source, scope, user_id)

        memory_file = Path(workspace_dir) / "MEMORY.md"
        if memory_file.exists():
            files_to_scan.append((memory_file, "memory", "shared", None))

        if memory_dir.exists():
            for file_path in memory_dir.rglob("*.md"):
                rel_parts = file_path.relative_to(workspace_dir).parts
                if any(part.startswith('.') for part in rel_parts):
                    continue
                # Dream diaries are narrative reflections produced by Deep
                # Dream; their factual content has already been distilled
                # into MEMORY.md. Indexing them adds noisy near-duplicates
                # that crowd out the authoritative entry in retrieval.
                if "dreams" in rel_parts:
                    continue
                if "daily" in rel_parts:
                    if "users" in rel_parts or len(rel_parts) > 3:
                        user_idx = rel_parts.index("daily") + 1
                        user_id = rel_parts[user_idx] if user_idx < len(rel_parts) else None
                        scope = "user"
                    else:
                        user_id = None
                        scope = "shared"
                elif "users" in rel_parts:
                    user_idx = rel_parts.index("users") + 1
                    user_id = rel_parts[user_idx] if user_idx < len(rel_parts) else None
                    scope = "user"
                else:
                    user_id = None
                    scope = "shared"
                files_to_scan.append((file_path, "memory", scope, user_id))

        from common import state_dir
        from config import conf
        knowledge_dir: Optional[Path] = None
        if conf().get("knowledge", True):
            # Resolve through state_dir so an Agent without its own knowledge/
            # scans the shared base rather than an empty (or missing) local one.
            knowledge_dir = Path(state_dir.knowledge_dir(base=workspace_dir))
            if knowledge_dir.exists():
                for file_path in knowledge_dir.rglob("*.md"):
                    # The root index.md / log.md only restate pages indexed on
                    # their own, and change on every page write, which re-embeds
                    # the whole file each time.
                    if file_path.parent == knowledge_dir and file_path.name in ("index.md", "log.md"):
                        continue
                    files_to_scan.append((file_path, "knowledge", "shared", None))

        # Pass 1: inline chunking + change detection. Inlined (instead of
        # calling self._prepare_file_for_sync) so this method does not depend
        # on any sibling helpers — keeps it robust against partial reloads
        # where the class object is older than the method's source.
        pending: List[Dict[str, Any]] = []
        workspace_dir_path = self.config.get_workspace()
        from common.log import logger

        # Roots a scanned file may legitimately sit under, most specific first,
        # each paired with the prefix its files are keyed under. Resolved once
        # rather than per file: shared_root() goes through the Agent registry.
        # knowledge_dir comes first so a knowledge file keys the same whether it
        # is this Agent's own copy or the shared one it fell back to.
        index_roots: List[Tuple[Path, str]] = []
        if knowledge_dir is not None:
            index_roots.append((knowledge_dir, "knowledge"))
        index_roots.append((Path(workspace_dir_path), ""))
        try:
            index_roots.append((state_dir.shared_root(), ""))
        except Exception:
            # No resolvable shared root (registry not ready). The workspace
            # still covers every file that is not a shared fallback.
            pass

        scanned: Dict[str, set] = {}

        for file_path, source, scope, user_id in files_to_scan:
            rel_path = _index_rel_path(file_path, index_roots)
            if rel_path is None:
                # Defensive: every scan target above resolves under one of the
                # roots. Skip just this file so one oddity cannot cost the Agent
                # its whole memory, and say so rather than dropping it silently.
                logger.warning(
                    f"[MemoryManager] Skipping {file_path}: it sits under none of "
                    f"this Agent's roots, so it has no stable index key"
                )
                continue
            # Recorded before the read, so a file that is present but unreadable
            # still counts as scanned and keeps the rows it already has.
            scanned.setdefault(source, set()).add(rel_path)
            try:
                content = file_path.read_text(encoding='utf-8')
            except Exception as e:
                # Was silent, which made a half-indexed workspace look healthy.
                logger.warning(f"[MemoryManager] Skipping {file_path}: cannot read it ({e})")
                continue
            file_hash = MemoryStorage.compute_hash(content)
            if self.storage.get_file_hash(rel_path) == file_hash:
                continue
            # Markdown files (memory + knowledge) get structure-aware chunking;
            # anything else (rare) falls back to the plain char splitter.
            if file_path.suffix.lower() == '.md':
                chunks = self.chunker.chunk_markdown(content)
            else:
                chunks = self.chunker.chunk_text(content)
            if not chunks:
                continue
            pending.append({
                "file_path": file_path,
                "rel_path": rel_path,
                "source": source,
                "scope": scope,
                "user_id": user_id,
                "file_hash": file_hash,
                "chunks": chunks,
                "texts": [c.text for c in chunks],
            })

        # Reconcile before the early return below: an index full of stale rows
        # is exactly the case where nothing changed and `pending` is empty.
        #
        # sync() only ever added and overwrote. Anything that left a scanned
        # root — a page the user deleted, or every shared page at once when an
        # Agent is switched to its own knowledge/ — stayed in the index and kept
        # being returned by memory_search long after no tool could open it.
        #
        # Only a source whose root resolved and exists is reconciled. An empty
        # scan set then means the files are genuinely gone, rather than that the
        # root was momentarily unresolvable, which must not cost a whole index.
        reconcilable = []
        if memory_dir.exists():
            reconcilable.append("memory")
        if knowledge_dir is not None and knowledge_dir.exists():
            reconcilable.append("knowledge")
        for source in reconcilable:
            try:
                stale = set(self.storage.list_paths(source)) - scanned.get(source, set())
            except Exception as e:
                logger.warning(f"[MemoryManager] Cannot reconcile {source} index: {e}")
                continue
            dropped = 0
            for stale_path in stale:
                try:
                    self.storage.delete_by_path(stale_path)
                    dropped += 1
                except Exception as e:
                    logger.warning(f"[MemoryManager] Cannot drop stale entry {stale_path}: {e}")
            if dropped:
                logger.info(
                    f"[MemoryManager] Dropped {dropped} stale {source} "
                    f"entries that are no longer on disk"
                )

        if not pending:
            self._dirty = False
            return

        # Pass 2: single batched embed across all pending chunks.
        # CRITICAL: never touch the index until we hold valid embeddings.
        # If embed_batch fails, leave the existing index intact (chunks +
        # file_hash) so the next sync will retry the same files. Writing
        # NULL embeddings + updating file_hash here would mark the file as
        # "successfully synced" and silently strand it without vectors.
        all_texts: List[str] = []
        for entry in pending:
            all_texts.extend(entry["texts"])

        if not self.embedding_provider:
            # No provider configured at all (legacy keyword-only). Persist
            # chunks without embeddings — this is the user's intent.
            all_embeddings: List[Optional[List[float]]] = [None] * len(all_texts)
        else:
            try:
                all_embeddings = self.embedding_provider.embed_batch(all_texts)
            except Exception as e:
                from common.log import logger
                logger.error(
                    f"[MemoryManager] Batch embedding failed for {len(all_texts)} "
                    f"chunks across {len(pending)} files: {e}. "
                    f"Index left untouched; will retry on next sync."
                )
                # Bail before touching storage. self._dirty stays True so
                # callers know there is pending work.
                return

        # Pass 3: inline persist — same self-contained reasoning as Pass 1.
        cursor = 0
        for entry in pending:
            n = len(entry["texts"])
            entry_embeddings = all_embeddings[cursor:cursor + n]
            cursor += n

            rel_path = entry["rel_path"]
            self.storage.delete_by_path(rel_path)
            if os.sep != "/":
                # Keys used to be spelled with the platform separator. Drop that
                # row too, so a Windows index carried over from an older build
                # does not keep a second copy of the same file under
                # "knowledge\note.md" and return it twice.
                self.storage.delete_by_path(rel_path.replace("/", os.sep))
            memory_chunks = []
            for chunk, embedding in zip(entry["chunks"], entry_embeddings):
                chunk_id = self._generate_chunk_id(rel_path, chunk.start_line, chunk.end_line)
                chunk_hash = MemoryStorage.compute_hash(chunk.text)
                memory_chunks.append(MemoryChunk(
                    id=chunk_id,
                    user_id=entry["user_id"],
                    scope=entry["scope"],
                    source=entry["source"],
                    path=rel_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    text=chunk.text,
                    embedding=embedding,
                    hash=chunk_hash,
                    metadata=None,
                ))
            self.storage.save_chunks_batch(memory_chunks)
            stat = entry["file_path"].stat()
            self.storage.update_file_metadata(
                path=rel_path,
                source=entry["source"],
                file_hash=entry["file_hash"],
                mtime=int(stat.st_mtime),
                size=stat.st_size,
            )

        # Stamp the chunker version only when we rebuilt from an empty index,
        # i.e. every chunk in it was produced by the current algorithm. An
        # index that already had files may still contain chunks from an older
        # chunker (file hashes do not change when only the chunker does), so it
        # stays unstamped and /memory status will suggest a rebuild.
        if files_before == 0:
            try:
                self.storage.set_meta(
                    "chunker_version", str(TextChunker.CHUNKER_VERSION)
                )
            except Exception:
                pass

        self._dirty = False

    def flush_memory(
        self,
        messages: list,
        user_id: Optional[str] = None,
        reason: str = "threshold",
        max_messages: int = 10,
        context_summary_callback=None,
    ) -> bool:
        """
        Flush conversation summary to daily memory file.

        Args:
            messages: Conversation message list
            user_id: Optional user ID
            reason: "threshold" | "overflow" | "daily_summary"
            max_messages: Max recent messages to include (0 = all)
            context_summary_callback: Optional callback(str) invoked with the
                daily summary text for in-context injection

        Returns:
            True if flush was dispatched
        """
        success = self.flush_manager.flush_from_messages(
            messages=messages,
            user_id=user_id,
            reason=reason,
            max_messages=max_messages,
            context_summary_callback=context_summary_callback,
        )
        if success:
            self._dirty = True
        return success
    
    def get_status(self) -> Dict[str, Any]:
        """Get memory status"""
        stats = self.storage.get_stats()
        return {
            'chunks': stats['chunks'],
            'files': stats['files'],
            'workspace': str(self.config.get_workspace()),
            'dirty': self._dirty,
            'embedding_enabled': self.embedding_provider is not None,
            'embedding_provider': self.config.embedding_provider if self.embedding_provider else 'disabled',
            'embedding_model': self.config.embedding_model if self.embedding_provider else 'N/A',
            'search_mode': 'hybrid (vector + keyword)' if self.embedding_provider else 'keyword only (FTS5)',
            'rerank_enabled': self.reranker is not None,
        }
    
    def mark_dirty(self):
        """Mark memory as dirty (needs sync)"""
        self._dirty = True
    
    def close(self):
        """Close memory manager and release resources"""
        self.storage.close()
    
    # Helper methods
    
    def _generate_chunk_id(self, path: str, start_line: int, end_line: int) -> str:
        """Generate unique chunk ID"""
        content = f"{path}:{start_line}:{end_line}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    @staticmethod
    def _compute_temporal_decay(path: str, half_life_days: float = 30.0) -> float:
        """
        Compute temporal decay multiplier for dated memory files.
        
        Inspired by OpenClaw's temporal-decay: exponential decay based on file date.
        MEMORY.md and non-dated files are "evergreen" (no decay, multiplier=1.0).
        Daily files like memory/2025-03-01.md decay based on age.
        
        Formula: multiplier = exp(-ln2/half_life * age_in_days)
        """
        import re
        import math
        
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})\.md$', path)
        if not match:
            return 1.0  # evergreen: MEMORY.md, non-dated files
        
        try:
            file_date = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
            age_days = (datetime.now() - file_date).days
            if age_days <= 0:
                return 1.0
            
            decay_lambda = math.log(2) / half_life_days
            return math.exp(-decay_lambda * age_days)
        except (ValueError, OverflowError):
            return 1.0
    
    @staticmethod
    def _normalize_weights(vector_weight: float, keyword_weight: float) -> tuple:
        """Clamp fusion weights into a valid (non-negative, finite) pair.

        The weighted average below is renormalized over only the channels that
        actually returned a chunk, so only the *ratio* between the two weights
        matters. Negative and non-finite weights (NaN, +/-inf) are clamped to 0,
        and an all-zero pair falls back to equal weighting, so a misconfigured
        value can never produce a negative or meaningless combined score.
        """
        import math

        try:
            v = float(vector_weight)
            k = float(keyword_weight)
        except (TypeError, ValueError):
            return 0.5, 0.5
        v = v if (math.isfinite(v) and v > 0) else 0.0
        k = k if (math.isfinite(k) and k > 0) else 0.0
        if v == 0.0 and k == 0.0:
            return 0.5, 0.5
        return v, k

    @staticmethod
    def _rank_normalize(results: List[SearchResult]) -> Dict[tuple, float]:
        """Rank-normalize one channel's already-sorted results onto (0, 1].

        ``search_vector`` and ``search_keyword`` both return their results in
        descending relevance order, so the position index is the rank. The top
        hit maps to 1.0 and each later hit decays linearly to 1/N. This puts
        raw cosine similarity and the BM25-derived keyword score — which live
        on incommensurable scales — onto a common scale before fusion.

        :return: {(path, start_line, end_line): normalized_score}
        """
        n = len(results)
        if n == 0:
            return {}
        return {
            (r.path, r.start_line, r.end_line): (n - i) / n
            for i, r in enumerate(results)
        }

    def _merge_results(
        self,
        vector_results: List[SearchResult],
        keyword_results: List[SearchResult],
        vector_weight: float,
        keyword_weight: float
    ) -> List[SearchResult]:
        """Merge vector and keyword search results with temporal decay.

        Each channel is rank-normalized to a common (0, 1] scale first, then a
        chunk is scored by the weighted average over only the channels that
        actually returned it. A strong single-channel hit is therefore not
        diluted by a 0.0 from the missing channel, and the two channels' raw
        scores no longer have to be comparable to be fused fairly.
        """
        vector_weight, keyword_weight = self._normalize_weights(vector_weight, keyword_weight)
        vector_norm = self._rank_normalize(vector_results)
        keyword_norm = self._rank_normalize(keyword_results)

        # Keep the first (vector-first) result per chunk for reconstruction;
        # either channel carries the same snippet/source/path metadata.
        result_map: Dict[tuple, SearchResult] = {}
        for result in vector_results + keyword_results:
            key = (result.path, result.start_line, result.end_line)
            result_map.setdefault(key, result)

        merged_results = []
        for key in set(vector_norm) | set(keyword_norm):
            result = result_map[key]
            vec = vector_norm.get(key)
            kw = keyword_norm.get(key)
            hit_v = vec is not None
            hit_k = kw is not None
            numerator = (
                vector_weight * (vec if hit_v else 0.0)
                + keyword_weight * (kw if hit_k else 0.0)
            )
            denominator = (
                (vector_weight if hit_v else 0.0)
                + (keyword_weight if hit_k else 0.0)
            )
            combined_score = (numerator / denominator) if denominator > 0 else 0.0

            # Apply temporal decay for dated memory files
            combined_score *= self._compute_temporal_decay(result.path)

            merged_results.append(SearchResult(
                path=result.path,
                start_line=result.start_line,
                end_line=result.end_line,
                score=combined_score,
                snippet=result.snippet,
                source=result.source,
                user_id=result.user_id
            ))

        merged_results.sort(key=lambda r: r.score, reverse=True)
        return merged_results

    def _rerank(
        self,
        query: str,
        results: List[SearchResult]
    ) -> List[SearchResult]:
        """Precision-reorder merged candidates with a cross-encoder reranker.

        Replaces each candidate's fused score with the cross-encoder's
        relevance judgement (still subject to temporal decay), then re-sorts.
        Returns ``results`` unchanged when no reranker is configured, so the
        optional ``sentence-transformers`` dependency is never required.
        """
        if self.reranker is None or not results:
            return results

        documents = [r.snippet for r in results]
        scores = self.reranker.rerank(query, documents)

        reranked = []
        for result, score in zip(results, scores):
            decayed = score * self._compute_temporal_decay(result.path)
            reranked.append(SearchResult(
                path=result.path,
                start_line=result.start_line,
                end_line=result.end_line,
                score=decayed,
                snippet=result.snippet,
                source=result.source,
                user_id=result.user_id
            ))

        reranked.sort(key=lambda r: r.score, reverse=True)
        return reranked
