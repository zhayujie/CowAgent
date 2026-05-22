"""
Storage layer for memory using SQLite + FTS5

Provides vector and keyword search capabilities
"""

from __future__ import annotations
import sqlite3
import json
import hashlib
from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass


@dataclass
class MemoryChunk:
    """Represents a memory chunk with text and embedding"""
    id: str
    user_id: Optional[str]
    scope: str  # "shared" | "user" | "session"
    source: str  # "memory" | "session"
    path: str
    start_line: int
    end_line: int
    text: str
    embedding: Optional[List[float]]
    hash: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SearchResult:
    """Search result with score and snippet"""
    path: str
    start_line: int
    end_line: int
    score: float
    snippet: str
    source: str
    user_id: Optional[str] = None


class MemoryStorage:
    """SQLite-based storage with FTS5 for keyword search"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.fts5_available = False  # Track FTS5 availability
        self._init_db()
    
    def _check_fts5_support(self) -> bool:
        """Check if SQLite has FTS5 support"""
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts5_test USING fts5(test)")
            self.conn.execute("DROP TABLE IF EXISTS fts5_test")
            return True
        except sqlite3.OperationalError as e:
            if "no such module: fts5" in str(e):
                return False
            raise
    
    def _init_db(self):
        """Initialize database with schema"""
        try:
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            
            # Check FTS5 support
            self.fts5_available = self._check_fts5_support()
            if not self.fts5_available:
                from common.log import logger
                logger.debug("[MemoryStorage] FTS5 not available, using LIKE-based keyword search")
            
            # Check database integrity
            try:
                result = self.conn.execute("PRAGMA integrity_check").fetchone()
                if result[0] != 'ok':
                    print(f"⚠️  Database integrity check failed: {result[0]}")
                    print(f"   Recreating database...")
                    self.conn.close()
                    self.conn = None
                    # Remove corrupted database
                    self.db_path.unlink(missing_ok=True)
                    # Remove WAL files
                    Path(str(self.db_path) + '-wal').unlink(missing_ok=True)
                    Path(str(self.db_path) + '-shm').unlink(missing_ok=True)
                    # Reconnect to create new database
                    self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                    self.conn.row_factory = sqlite3.Row
            except sqlite3.DatabaseError:
                # Database is corrupted, recreate it
                print(f"⚠️  Database is corrupted, recreating...")
                if self.conn:
                    self.conn.close()
                    self.conn = None
                self.db_path.unlink(missing_ok=True)
                Path(str(self.db_path) + '-wal').unlink(missing_ok=True)
                Path(str(self.db_path) + '-shm').unlink(missing_ok=True)
                self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                self.conn.row_factory = sqlite3.Row
            
            # Enable WAL mode for better concurrency
            self.conn.execute("PRAGMA journal_mode=WAL")
            # Set busy timeout to avoid "database is locked" errors
            self.conn.execute("PRAGMA busy_timeout=5000")
        except Exception as e:
            print(f"⚠️  Unexpected error during database initialization: {e}")
            raise
        
        # Create chunks table with embeddings
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                scope TEXT NOT NULL DEFAULT 'shared',
                source TEXT NOT NULL DEFAULT 'memory',
                path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT,
                hash TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        # Create indexes
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_user 
            ON chunks(user_id)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_scope 
            ON chunks(scope)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_hash 
            ON chunks(path, hash)
        """)
        
        # Create FTS5 virtual table + triggers (only if supported).
        # Self-heal: if the previous process crashed mid-rebuild and left
        # triggers pointing at a missing chunks_fts (or vice versa), wipe
        # both sides and recreate cleanly. Otherwise next chunks INSERT
        # will fail with "no such table: chunks_fts".
        if self.fts5_available:
            if self._fts5_state_inconsistent():
                from common.log import logger
                logger.warning(
                    "[MemoryStorage] FTS5 state inconsistent (triggers/table mismatch). "
                    "Resetting chunks_fts to recover."
                )
                self.conn.execute("DROP TRIGGER IF EXISTS chunks_ai")
                self.conn.execute("DROP TRIGGER IF EXISTS chunks_ad")
                self.conn.execute("DROP TRIGGER IF EXISTS chunks_au")
                self.conn.execute("DROP TABLE IF EXISTS chunks_fts")
                self.conn.commit()
            self._create_fts5_objects()

            # Probe FTS5 shadow tables. The schema may be intact but the
            # internal _data/_idx/_docsize blob can still be corrupt — that
            # surfaces as "database disk image is malformed" on bm25 / MATCH.
            # We rebuild from the chunks table when that happens; data isn't
            # lost because chunks (the content table) is the source of truth.
            if self._fts5_shadow_corrupt():
                from common.log import logger
                logger.warning(
                    "[MemoryStorage] FTS5 shadow tables corrupt; rebuilding from chunks."
                )
                self._rebuild_fts5_from_chunks()

        # Create files metadata table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'memory',
                hash TEXT NOT NULL,
                mtime INTEGER NOT NULL,
                size INTEGER NOT NULL,
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        self.conn.commit()

    def _fts5_state_inconsistent(self) -> bool:
        """Detect a half-broken FTS5 setup (e.g. trigger exists but table doesn't)."""
        try:
            row = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
            ).fetchone()
            table_exists = row is not None
            row = self.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name IN ('chunks_ai','chunks_ad','chunks_au')"
            ).fetchone()
            trigger_count = int(row[0]) if row else 0
        except Exception:
            return False
        # Healthy = both present (3 triggers + table) or both absent.
        return table_exists != (trigger_count > 0)

    def _create_fts5_objects(self):
        """Create chunks_fts virtual table and the 3 sync triggers.

        Idempotent: uses IF NOT EXISTS. Caller must hold self.conn.
        """
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                text,
                id UNINDEXED,
                user_id UNINDEXED,
                path UNINDEXED,
                source UNINDEXED,
                scope UNINDEXED,
                content='chunks',
                content_rowid='rowid'
            )
        """)
        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, text, id, user_id, path, source, scope)
                VALUES (new.rowid, new.text, new.id, new.user_id, new.path, new.source, new.scope);
            END
        """)
        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                DELETE FROM chunks_fts WHERE rowid = old.rowid;
            END
        """)
        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                UPDATE chunks_fts SET text = new.text, id = new.id,
                                     user_id = new.user_id, path = new.path,
                                     source = new.source, scope = new.scope
                WHERE rowid = new.rowid;
            END
        """)

    def reset_fts5(self):
        """Drop and recreate chunks_fts + triggers in one transaction.

        Used by rebuild_index to recover from FTS5 shadow-table corruption
        (bm25/ORDER BY rank may raise "database disk image is malformed"
        even when raw MATCH still works).

        Triggers must be dropped first; otherwise the next chunks INSERT/DELETE
        on the existing connection will hit "no such table: chunks_fts".
        """
        if not self.fts5_available:
            return
        self.conn.execute("DROP TRIGGER IF EXISTS chunks_ai")
        self.conn.execute("DROP TRIGGER IF EXISTS chunks_ad")
        self.conn.execute("DROP TRIGGER IF EXISTS chunks_au")
        self.conn.execute("DROP TABLE IF EXISTS chunks_fts")
        self._create_fts5_objects()
        self.conn.commit()

    def _fts5_shadow_corrupt(self) -> bool:
        """Probe whether bm25 over chunks_fts errors out at startup.

        Schema (table + triggers) can be intact while the underlying
        FTS5 shadow blobs are malformed — typically because the previous
        process crashed mid-write or wrote with a different SQLite build.
        A cheap MATCH probe surfaces it immediately."""
        try:
            self.conn.execute(
                "SELECT bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH 'a' LIMIT 1"
            ).fetchone()
            return False
        except sqlite3.DatabaseError as e:
            msg = str(e).lower()
            return "malformed" in msg or "corrupt" in msg
        except Exception:
            # Any other error (e.g. table missing) is handled by the
            # state-inconsistent path; treat as healthy here.
            return False

    def _rebuild_fts5_from_chunks(self):
        """Drop FTS5, recreate it, then INSERT every row from chunks.

        Safe data-wise: chunks (the content table) is the source of truth.
        Done in one transaction so a crash leaves either fully old or fully
        new state, not a partial rebuild.
        """
        # Reset schema first; this clears any malformed shadow blobs.
        self.reset_fts5()
        # Re-feed content. Triggers handle future writes automatically.
        self.conn.execute("""
            INSERT INTO chunks_fts(rowid, text, id, user_id, path, source, scope)
            SELECT rowid, text, id, user_id, path, source, scope FROM chunks
        """)
        self.conn.commit()

    def save_chunk(self, chunk: MemoryChunk):
        """Save a memory chunk"""
        self.conn.execute("""
            INSERT OR REPLACE INTO chunks 
            (id, user_id, scope, source, path, start_line, end_line, text, embedding, hash, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
        """, (
            chunk.id,
            chunk.user_id,
            chunk.scope,
            chunk.source,
            chunk.path,
            chunk.start_line,
            chunk.end_line,
            chunk.text,
            json.dumps(chunk.embedding) if chunk.embedding else None,
            chunk.hash,
            json.dumps(chunk.metadata) if chunk.metadata else None
        ))
        self.conn.commit()
    
    def save_chunks_batch(self, chunks: List[MemoryChunk]):
        """Save multiple chunks in a batch"""
        self.conn.executemany("""
            INSERT OR REPLACE INTO chunks 
            (id, user_id, scope, source, path, start_line, end_line, text, embedding, hash, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
        """, [
            (
                c.id, c.user_id, c.scope, c.source, c.path,
                c.start_line, c.end_line, c.text,
                json.dumps(c.embedding) if c.embedding else None,
                c.hash,
                json.dumps(c.metadata) if c.metadata else None
            )
            for c in chunks
        ])
        self.conn.commit()
    
    def get_chunk(self, chunk_id: str) -> Optional[MemoryChunk]:
        """Get a chunk by ID"""
        row = self.conn.execute("""
            SELECT * FROM chunks WHERE id = ?
        """, (chunk_id,)).fetchone()
        
        if not row:
            return None
        
        return self._row_to_chunk(row)
    
    def search_vector(
        self,
        query_embedding: List[float],
        user_id: Optional[str] = None,
        scopes: List[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Vector similarity search using in-memory cosine similarity
        (sqlite-vec can be added later for better performance)
        """
        if scopes is None:
            scopes = ["shared"]
            if user_id:
                scopes.append("user")
        
        # Build query
        scope_placeholders = ','.join('?' * len(scopes))
        params = scopes
        
        if user_id:
            query = f"""
                SELECT * FROM chunks 
                WHERE scope IN ({scope_placeholders})
                AND (scope = 'shared' OR user_id = ?)
                AND embedding IS NOT NULL
            """
            params.append(user_id)
        else:
            query = f"""
                SELECT * FROM chunks 
                WHERE scope IN ({scope_placeholders})
                AND embedding IS NOT NULL
            """
        
        rows = self.conn.execute(query, params).fetchall()

        # Calculate cosine similarity. We probe the first row's dim to fail
        # loudly on a query/index dim mismatch — otherwise every doc would
        # score 0 silently, leaving the user wondering why search broke.
        results = []
        query_dim = len(query_embedding)
        if rows:
            first = json.loads(rows[0]['embedding'])
            if isinstance(first, list) and len(first) != query_dim:
                raise ValueError(
                    f"Embedding dim mismatch: query is {query_dim}-dim but "
                    f"index stores {len(first)}-dim vectors. The configured "
                    f"embedding model differs from the one that built the "
                    f"index — run /memory rebuild-index to re-embed."
                )

        for row in rows:
            embedding = json.loads(row['embedding'])
            similarity = self._cosine_similarity(query_embedding, embedding)

            if similarity > 0:
                results.append((similarity, row))
        
        # Sort by similarity and limit
        results.sort(key=lambda x: x[0], reverse=True)
        results = results[:limit]
        
        return [
            SearchResult(
                path=row['path'],
                start_line=row['start_line'],
                end_line=row['end_line'],
                score=score,
                snippet=self._truncate_text(row['text'], 500),
                source=row['source'],
                user_id=row['user_id']
            )
            for score, row in results
        ]
    
    def search_keyword(
        self,
        query: str,
        user_id: Optional[str] = None,
        scopes: List[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Keyword search using FTS5 + LIKE fallback

        Strategy:
        1. If FTS5 available and healthy: try FTS5 first
        2. Always fall back to LIKE for CJK queries
        3. If FTS5 fails OR returns empty for non-CJK, also try LIKE so a
           broken FTS5 shadow table doesn't silently kill keyword search.
        """
        if scopes is None:
            scopes = ["shared"]
            if user_id:
                scopes.append("user")

        if self.fts5_available:
            fts_results = self._search_fts5(query, user_id, scopes, limit)
            if fts_results:
                return fts_results

        return self._search_like(query, user_id, scopes, limit)
    
    def _search_fts5(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int
    ) -> List[SearchResult]:
        """FTS5 full-text search"""
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []
        
        scope_placeholders = ','.join('?' * len(scopes))
        params = [fts_query] + scopes
        
        if user_id:
            sql_query = f"""
                SELECT chunks.*, bm25(chunks_fts) as rank
                FROM chunks_fts
                JOIN chunks ON chunks.id = chunks_fts.id
                WHERE chunks_fts MATCH ? 
                AND chunks.scope IN ({scope_placeholders})
                AND (chunks.scope = 'shared' OR chunks.user_id = ?)
                ORDER BY rank
                LIMIT ?
            """
            params.extend([user_id, limit])
        else:
            sql_query = f"""
                SELECT chunks.*, bm25(chunks_fts) as rank
                FROM chunks_fts
                JOIN chunks ON chunks.id = chunks_fts.id
                WHERE chunks_fts MATCH ? 
                AND chunks.scope IN ({scope_placeholders})
                ORDER BY rank
                LIMIT ?
            """
            params.append(limit)
        
        try:
            rows = self.conn.execute(sql_query, params).fetchall()
            return [
                SearchResult(
                    path=row['path'],
                    start_line=row['start_line'],
                    end_line=row['end_line'],
                    score=self._bm25_rank_to_score(row['rank']),
                    snippet=self._truncate_text(row['text'], 500),
                    source=row['source'],
                    user_id=row['user_id']
                )
                for row in rows
            ]
        except Exception as e:
            from common.log import logger
            logger.error(
                f"[MemoryStorage] FTS5 search failed (caller will fall back to LIKE): {e}"
            )
            return []
    
    def _search_like(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int
    ) -> List[SearchResult]:
        """LIKE-based search.

        Used as the keyword-search fallback when FTS5 is unavailable, fails,
        or returns empty. Supports both CJK runs and ASCII word tokens so it
        can serve as a true safety net for any query.
        """
        import re
        # CJK runs (2+ chars) + ASCII word tokens (3+ chars to avoid noise)
        cjk_words = re.findall(r'[\u4e00-\u9fff]{2,}', query)
        ascii_words = [t for t in re.findall(r'[A-Za-z0-9_]+', query) if len(t) >= 3]
        words = cjk_words + ascii_words
        if not words:
            return []

        scope_placeholders = ','.join('?' * len(scopes))

        # Build LIKE conditions for each word (case-insensitive for ASCII)
        like_conditions = []
        params = []
        for word in words:
            like_conditions.append("LOWER(text) LIKE ?")
            params.append(f'%{word.lower()}%')
        
        where_clause = ' OR '.join(like_conditions)
        params.extend(scopes)
        
        if user_id:
            sql_query = f"""
                SELECT * FROM chunks
                WHERE ({where_clause})
                AND scope IN ({scope_placeholders})
                AND (scope = 'shared' OR user_id = ?)
                LIMIT ?
            """
            params.extend([user_id, limit])
        else:
            sql_query = f"""
                SELECT * FROM chunks
                WHERE ({where_clause})
                AND scope IN ({scope_placeholders})
                LIMIT ?
            """
            params.append(limit)
        
        try:
            rows = self.conn.execute(sql_query, params).fetchall()
            return [
                SearchResult(
                    path=row['path'],
                    start_line=row['start_line'],
                    end_line=row['end_line'],
                    score=0.5,  # Fixed score for LIKE search
                    snippet=self._truncate_text(row['text'], 500),
                    source=row['source'],
                    user_id=row['user_id']
                )
                for row in rows
            ]
        except Exception as e:
            from common.log import logger
            logger.error(f"[MemoryStorage] LIKE search failed: {e}")
            return []
    
    def delete_by_path(self, path: str):
        """Delete all chunks from a file"""
        self.conn.execute("""
            DELETE FROM chunks WHERE path = ?
        """, (path,))
        self.conn.commit()
    
    def get_file_hash(self, path: str) -> Optional[str]:
        """Get stored file hash"""
        row = self.conn.execute("""
            SELECT hash FROM files WHERE path = ?
        """, (path,)).fetchone()
        return row['hash'] if row else None
    
    def update_file_metadata(self, path: str, source: str, file_hash: str, mtime: int, size: int):
        """Update file metadata"""
        self.conn.execute("""
            INSERT OR REPLACE INTO files (path, source, hash, mtime, size, updated_at)
            VALUES (?, ?, ?, ?, ?, strftime('%s', 'now'))
        """, (path, source, file_hash, mtime, size))
        self.conn.commit()
    
    def get_stats(self) -> Dict[str, int]:
        """Get storage statistics"""
        chunks_count = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM chunks
        """).fetchone()['cnt']

        files_count = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM files
        """).fetchone()['cnt']

        embedded_count = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM chunks WHERE embedding IS NOT NULL
        """).fetchone()['cnt']

        return {
            'chunks': chunks_count,
            'files': files_count,
            'embedded': embedded_count,
        }
    
    def close(self):
        """Close database connection"""
        if self.conn:
            try:
                self.conn.commit()  # Ensure all changes are committed
                self.conn.close()
                self.conn = None  # Mark as closed
            except Exception as e:
                print(f"⚠️  Error closing database connection: {e}")
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        try:
            self.close()
        except Exception:
            pass  # Ignore errors during cleanup
    
    # Helper methods
    
    def _row_to_chunk(self, row) -> MemoryChunk:
        """Convert database row to MemoryChunk"""
        return MemoryChunk(
            id=row['id'],
            user_id=row['user_id'],
            scope=row['scope'],
            source=row['source'],
            path=row['path'],
            start_line=row['start_line'],
            end_line=row['end_line'],
            text=row['text'],
            embedding=json.loads(row['embedding']) if row['embedding'] else None,
            hash=row['hash'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    @staticmethod
    def _contains_cjk(text: str) -> bool:
        """Check if text contains CJK (Chinese/Japanese/Korean) characters"""
        import re
        return bool(re.search(r'[\u4e00-\u9fff]', text))
    
    @staticmethod
    def _build_fts_query(raw_query: str) -> Optional[str]:
        """
        Build FTS5 query from raw text
        
        Works best for English and word-based languages.
        For CJK characters, LIKE search will be used as fallback.
        """
        import re
        # Extract words (primarily English words and numbers)
        tokens = re.findall(r'[A-Za-z0-9_]+', raw_query)
        if not tokens:
            return None
        
        # Quote tokens for exact matching
        quoted = [f'"{t}"' for t in tokens]
        # Use OR for more flexible matching
        return ' OR '.join(quoted)
    
    @staticmethod
    def _bm25_rank_to_score(rank: float) -> float:
        """Convert BM25 rank to 0-1 score"""
        normalized = max(0, rank) if rank is not None else 999
        return 1 / (1 + normalized)
    
    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        """Truncate text to max characters"""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."
    
    @staticmethod
    def compute_hash(content: str) -> str:
        """Compute SHA256 hash of content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
