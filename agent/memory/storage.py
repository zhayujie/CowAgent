"""
Storage layer for memory using SQLite + FTS5

Provides vector and keyword search capabilities
"""

from __future__ import annotations
import re
import sqlite3
import json
import hashlib
import threading
from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    np = None  # type: ignore[assignment]

# UPSERT (INSERT … ON CONFLICT DO UPDATE) requires SQLite ≥ 3.24.0 (2018).
# Older systems (e.g. CentOS 7 ships SQLite 3.7) fall back to INSERT OR REPLACE,
# which risks FTS5 rowid drift on chunk updates (see save_chunk docstring).
_HAS_UPSERT = sqlite3.sqlite_version_info >= (3, 24, 0)

# ---------------------------------------------------------------------------
# CJK character ranges, compiled once at module load.
# Covers: CJK Symbols/Punctuation, Japanese kana (hiragana + katakana),
#         CJK Unified Ideographs + Extension A, Korean syllables (Hangul),
#         CJK Compatibility Ideographs, and CJK Extension B–F.
# ---------------------------------------------------------------------------
_CJK_RANGES = (
    r'\u3000-\u30ff'          # CJK Symbols/Punctuation + Japanese kana
    r'\u3400-\u9fff'          # CJK Unified Ideographs (incl. Extension A)
    r'\uac00-\ud7af'          # Korean syllables (Hangul)
    r'\uf900-\ufaff'          # CJK Compatibility Ideographs
    r'\U00020000-\U0002fa1f'  # CJK Extension B–F
)
_RE_CONTAINS_CJK   = re.compile(f'[{_CJK_RANGES}]')
_RE_CJK_WORDS      = re.compile(f'[{_CJK_RANGES}]+')
_RE_TRIGRAM_TOKENS = re.compile(f'[{_CJK_RANGES}]+|[A-Za-z0-9_]+')


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
        # RLock protects concurrent writes from the same process.
        # SQLite WAL mode handles read/write concurrency at the file level,
        # but same-process concurrent writes still need a Python-level lock.
        self._lock = threading.RLock()
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
            if not _HAS_UPSERT:
                from common.log import logger
                logger.warning(
                    "[MemoryStorage] SQLite %s < 3.24 — UPSERT unavailable. "
                    "Falling back to INSERT OR REPLACE; FTS5 rowid may drift on "
                    "chunk updates (rebuild index periodically to recover).",
                    sqlite3.sqlite_version,
                )
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

        # Internal key-value store for persistent flags (e.g. backfill tracking)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS _meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Create trigram FTS5 table for CJK / mixed-language search
        self.trigram_fts5_available = False
        if self.fts5_available:
            try:
                self.conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_trigram USING fts5(
                        text,
                        id UNINDEXED,
                        user_id UNINDEXED,
                        path UNINDEXED,
                        source UNINDEXED,
                        scope UNINDEXED,
                        content='chunks',
                        content_rowid='rowid',
                        tokenize='trigram case_sensitive 0'
                    )
                """)
                self.conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS chunks_trigram_ai
                    AFTER INSERT ON chunks BEGIN
                        INSERT INTO chunks_fts_trigram(rowid, text, id, user_id, path, source, scope)
                        VALUES (new.rowid, new.text, new.id, new.user_id, new.path, new.source, new.scope);
                    END
                """)
                self.conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS chunks_trigram_ad
                    AFTER DELETE ON chunks BEGIN
                        DELETE FROM chunks_fts_trigram WHERE rowid = old.rowid;
                    END
                """)
                self.conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS chunks_trigram_au
                    AFTER UPDATE ON chunks BEGIN
                        UPDATE chunks_fts_trigram
                        SET text=new.text, id=new.id, user_id=new.user_id,
                            path=new.path, source=new.source, scope=new.scope
                        WHERE rowid = new.rowid;
                    END
                """)
                # One-time backfill for existing rows.
                # NOTE: COUNT(*) on an FTS5 content table always returns 0, so we
                # use a persistent flag in _meta instead of counting trigram rows.
                backfill_done = self.conn.execute(
                    "SELECT 1 FROM _meta WHERE key = 'trigram_backfill_done'"
                ).fetchone()
                chunks_count = self.conn.execute(
                    "SELECT COUNT(*) as c FROM chunks"
                ).fetchone()['c']
                if chunks_count > 0 and not backfill_done:
                    self.conn.execute(
                        "INSERT INTO chunks_fts_trigram(chunks_fts_trigram) VALUES('rebuild')"
                    )
                    self.conn.execute(
                        "INSERT OR REPLACE INTO _meta(key, value) VALUES('trigram_backfill_done', '1')"
                    )
                self.trigram_fts5_available = True
            except Exception:
                from common.log import logger
                logger.warning("[MemoryStorage] trigram FTS5 unavailable, CJK search will use LIKE fallback", exc_info=True)
                self.trigram_fts5_available = False

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
        """Save a memory chunk (insert or update by id).

        Uses SQLite UPSERT (INSERT … ON CONFLICT DO UPDATE) instead of
        INSERT OR REPLACE.  INSERT OR REPLACE internally does DELETE+INSERT,
        which changes the row's rowid.  Because both FTS5 tables use
        content_rowid='rowid', a new rowid would leave the old FTS index
        entries pointing at a non-existent rowid and trigger
        "fts5: missing row N from content table" errors.
        ON CONFLICT DO UPDATE fires the AFTER UPDATE trigger (chunks_au /
        chunks_trigram_au) and keeps the original rowid intact.
        """
        if _HAS_UPSERT:
            _SQL = """
                INSERT INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                ON CONFLICT(id) DO UPDATE SET
                    user_id     = excluded.user_id,
                    scope       = excluded.scope,
                    source      = excluded.source,
                    path        = excluded.path,
                    start_line  = excluded.start_line,
                    end_line    = excluded.end_line,
                    text        = excluded.text,
                    embedding   = excluded.embedding,
                    hash        = excluded.hash,
                    metadata    = excluded.metadata,
                    updated_at  = strftime('%s', 'now')
            """
        else:
            _SQL = """
                INSERT OR REPLACE INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            """
        params = (
            chunk.id, chunk.user_id, chunk.scope, chunk.source, chunk.path,
            chunk.start_line, chunk.end_line, chunk.text,
            self._encode_embedding(chunk.embedding),
            chunk.hash,
            json.dumps(chunk.metadata) if chunk.metadata else None,
        )
        with self._lock:
            self.conn.execute(_SQL, params)
            self.conn.commit()

    def save_chunks_batch(self, chunks: List[MemoryChunk]):
        """Save multiple chunks in a batch (insert or update by id).

        See save_chunk for why UPSERT is used instead of INSERT OR REPLACE.
        """
        if _HAS_UPSERT:
            _SQL = """
                INSERT INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                ON CONFLICT(id) DO UPDATE SET
                    user_id     = excluded.user_id,
                    scope       = excluded.scope,
                    source      = excluded.source,
                    path        = excluded.path,
                    start_line  = excluded.start_line,
                    end_line    = excluded.end_line,
                    text        = excluded.text,
                    embedding   = excluded.embedding,
                    hash        = excluded.hash,
                    metadata    = excluded.metadata,
                    updated_at  = strftime('%s', 'now')
            """
        else:
            _SQL = """
                INSERT OR REPLACE INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            """
        params_list = [
            (
                c.id, c.user_id, c.scope, c.source, c.path,
                c.start_line, c.end_line, c.text,
                self._encode_embedding(c.embedding),
                c.hash,
                json.dumps(c.metadata) if c.metadata else None,
            )
            for c in chunks
        ]
        with self._lock:
            self.conn.executemany(_SQL, params_list)
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
        Vector similarity search using numpy-vectorized cosine similarity.
        All embeddings are loaded then scored in a single BLAS matrix-vector
        multiply, which is ~100x faster than the pure-Python per-row loop.
        """
        if scopes is None:
            scopes = ["shared"]
            if user_id:
                scopes.append("user")

        scope_placeholders = ','.join('?' * len(scopes))
        params = list(scopes)

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
        if not rows:
            return []

        # Parse embeddings and build a (N, D) matrix in one pass.
        # New rows store BLOB bytes (np.frombuffer); legacy rows fall back to JSON.
        # Filter out rows whose embedding dimension differs from the query —
        # mixing dimensions would cause np.array() to produce an object array
        # and matrix @ q_vec to raise ValueError.
        expected_dim = len(query_embedding)
        valid_rows = []
        vectors = []
        for row in rows:
            vec = self._decode_embedding(row['embedding'])
            if not vec:
                continue
            if len(vec) != expected_dim:
                from common.log import logger
                logger.warning(
                    "[MemoryStorage] Skipping chunk %s: embedding dim %d != query dim %d",
                    row['id'], len(vec), expected_dim
                )
                continue
            valid_rows.append(row)
            vectors.append(vec)

        if not vectors:
            return []

        if _HAS_NUMPY:
            matrix = np.array(vectors, dtype=np.float32)        # (N, D)
            q_vec = np.array(query_embedding, dtype=np.float32)  # (D,)

            # Vectorized cosine similarity: dot(matrix, q) / (||matrix|| * ||q||)
            dots = matrix @ q_vec                                # (N,)
            row_norms = np.linalg.norm(matrix, axis=1)           # (N,)
            q_norm = float(np.linalg.norm(q_vec))
            denominators = row_norms * q_norm
            np.maximum(denominators, 1e-10, out=denominators)    # avoid div-by-zero
            sims = dots / denominators                           # (N,)

            # Select TopK using argpartition (O(N) average), then sort only those K
            k = min(limit, len(valid_rows))
            top_idx = np.argpartition(sims, -k)[-k:]
            top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]

            return [
                SearchResult(
                    path=valid_rows[i]['path'],
                    start_line=valid_rows[i]['start_line'],
                    end_line=valid_rows[i]['end_line'],
                    score=float(sims[i]),
                    snippet=self._truncate_text(valid_rows[i]['text'], 500),
                    source=valid_rows[i]['source'],
                    user_id=valid_rows[i]['user_id']
                )
                for i in top_idx
                if sims[i] > 0
            ]
        else:
            # Pure-Python cosine similarity fallback (numpy not installed)
            import math
            q = query_embedding
            q_norm = math.sqrt(sum(x * x for x in q)) or 1e-10
            scored = []
            for i, vec in enumerate(vectors):
                dot = sum(a * b for a, b in zip(vec, q))
                v_norm = math.sqrt(sum(x * x for x in vec)) or 1e-10
                sim = dot / (v_norm * q_norm)
                if sim > 0:
                    scored.append((sim, valid_rows[i]))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                SearchResult(
                    path=row['path'],
                    start_line=row['start_line'],
                    end_line=row['end_line'],
                    score=sim,
                    snippet=self._truncate_text(row['text'], 500),
                    source=row['source'],
                    user_id=row['user_id']
                )
                for sim, row in scored[:limit]
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

        # Step 1: Standard FTS5 (unicode61) — pure ASCII queries only.
        # Skipped when query contains any CJK characters: unicode61 tokenises CJK
        # as individual characters without forming meaningful tokens, so it would
        # match only the ASCII portion of a mixed query (e.g. "Python" from
        # "Python教程") and silently discard the CJK part.  Those queries go
        # directly to Step 2 (trigram), which handles both ASCII and CJK together.
        fts1_attempted = False
        if (self.fts5_available
                and not MemoryStorage._contains_cjk(query)
                and MemoryStorage._build_fts_query(query)):
            fts1_attempted = True
            fts_results = self._search_fts5(query, user_id, scopes, limit)
            if fts_results:
                return fts_results

        # Step 2: Trigram FTS5 — CJK/mixed queries, plus fallback when unicode61
        # returned nothing (trigram indexes all scripts with 3-char sliding windows,
        # so it can catch terms that unicode61 tokenisation misses).
        if self.trigram_fts5_available and (
            MemoryStorage._contains_cjk(query) or fts1_attempted
        ):
            trigram_results = self._search_fts5_trigram(query, user_id, scopes, limit)
            if trigram_results:
                return trigram_results

        # Step 3: LIKE fallback — last resort (FTS5 unavailable, or CJK tokens
        # shorter than 3 characters that trigram cannot match, e.g. a single-char query).
        if not self.fts5_available or MemoryStorage._contains_cjk(query):
            return self._search_like(query, user_id, scopes, limit)

        return []
    
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
                JOIN chunks ON chunks.rowid = chunks_fts.rowid
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
                JOIN chunks ON chunks.rowid = chunks_fts.rowid
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
        except Exception:
            from common.log import logger
            logger.warning("[MemoryStorage] _search_fts5 failed, returning empty", exc_info=True)
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
        or returns empty. Supports both CJK runs (1+ chars) and ASCII word
        tokens (3+ chars) so it can serve as a true safety net for any query.
        """
        # CJK runs (1+ chars, wide Unicode range) + ASCII words (3+ chars to avoid noise)
        cjk_words = _RE_CJK_WORDS.findall(query)
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
            results = []
            for row in rows:
                # Dynamic score: reward chunks that contain more of the query words.
                # Use all tokens (CJK + ASCII) so pure-ASCII queries are not skipped.
                # matched_count is always ≥1 because the WHERE clause uses OR, but
                # guard defensively so unexpected zero-match rows are never surfaced.
                text_lower = row['text'].lower()
                matched_count = sum(1 for w in words if w.lower() in text_lower)
                if matched_count == 0:
                    continue
                score = min(0.85, 0.3 + 0.15 * matched_count)
                results.append(SearchResult(
                    path=row['path'],
                    start_line=row['start_line'],
                    end_line=row['end_line'],
                    score=score,
                    snippet=self._truncate_text(row['text'], 500),
                    source=row['source'],
                    user_id=row['user_id']
                ))
            results.sort(key=lambda r: r.score, reverse=True)
            return results
        except Exception:
            from common.log import logger
            logger.warning("[MemoryStorage] _search_like failed, returning empty", exc_info=True)
            return []

    def delete_by_path(self, path: str):
        """Delete all chunks from a file"""
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
            self.conn.commit()

    def get_file_hash(self, path: str) -> Optional[str]:
        """Get stored file hash"""
        row = self.conn.execute("""
            SELECT hash FROM files WHERE path = ?
        """, (path,)).fetchone()
        return row['hash'] if row else None

    def update_file_metadata(self, path: str, source: str, file_hash: str, mtime: int, size: int):
        """Update file metadata"""
        with self._lock:
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
                from common.log import logger
                logger.warning("[MemoryStorage] Error closing database connection: %s", e)
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        try:
            self.close()
        except Exception:
            pass  # Ignore errors during cleanup
    
    # Helper methods

    @staticmethod
    def _encode_embedding(embedding: Optional[List[float]]) -> Optional[bytes]:
        """Encode embedding as float32 BLOB bytes (~6x smaller and faster than JSON).
        Falls back to struct.pack when numpy is unavailable."""
        if embedding is None:
            return None
        if _HAS_NUMPY:
            return np.array(embedding, dtype=np.float32).tobytes()
        import struct
        return struct.pack(f'{len(embedding)}f', *embedding)

    @staticmethod
    def _decode_embedding(raw) -> Optional[List[float]]:
        """Decode embedding from BLOB bytes or legacy JSON string.
        Handles both numpy and numpy-free environments."""
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            if _HAS_NUMPY:
                return np.frombuffer(raw, dtype=np.float32).tolist()
            import struct
            n = len(raw) // 4
            return list(struct.unpack(f'{n}f', raw))
        # Legacy JSON format written by older versions
        return json.loads(raw)

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
            embedding=self._decode_embedding(row['embedding']),
            hash=row['hash'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )
    
    @staticmethod
    def _contains_cjk(text: str) -> bool:
        """Check if text contains CJK or related characters (Chinese, Japanese, Korean)."""
        return bool(_RE_CONTAINS_CJK.search(text))
    
    @staticmethod
    def _build_trigram_query(raw_query: str) -> Optional[str]:
        """
        Build FTS5 MATCH query for the trigram tokenizer.
        Extracts CJK sequences (including single characters) and ASCII words,
        joining them with AND so all terms must appear in the matched chunk.
        """
        tokens = _RE_TRIGRAM_TOKENS.findall(raw_query)
        tokens = [t for t in tokens if t]
        if not tokens:
            return None
        # Escape embedded double-quotes (FTS5 uses "" inside quoted phrases)
        quoted = [f'"{t.replace(chr(34), chr(34)*2)}"' for t in tokens]
        return ' AND '.join(quoted)

    def _search_fts5_trigram(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int
    ) -> List[SearchResult]:
        """Trigram FTS5 search — handles CJK and mixed queries with BM25 ranking."""
        trigram_query = self._build_trigram_query(query)
        if not trigram_query:
            return []

        scope_placeholders = ','.join('?' * len(scopes))
        params = [trigram_query] + list(scopes)

        if user_id:
            sql = f"""
                SELECT chunks.*, bm25(chunks_fts_trigram) as rank
                FROM chunks_fts_trigram
                JOIN chunks ON chunks.rowid = chunks_fts_trigram.rowid
                WHERE chunks_fts_trigram MATCH ?
                AND chunks.scope IN ({scope_placeholders})
                AND (chunks.scope = 'shared' OR chunks.user_id = ?)
                ORDER BY rank
                LIMIT ?
            """
            params.extend([user_id, limit])
        else:
            sql = f"""
                SELECT chunks.*, bm25(chunks_fts_trigram) as rank
                FROM chunks_fts_trigram
                JOIN chunks ON chunks.rowid = chunks_fts_trigram.rowid
                WHERE chunks_fts_trigram MATCH ?
                AND chunks.scope IN ({scope_placeholders})
                ORDER BY rank
                LIMIT ?
            """
            params.append(limit)

        try:
            rows = self.conn.execute(sql, params).fetchall()
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
        except Exception:
            from common.log import logger
            logger.warning("[MemoryStorage] _search_fts5_trigram failed, returning empty", exc_info=True)
            return []

    @staticmethod
    def _build_fts_query(raw_query: str) -> Optional[str]:
        """
        Build FTS5 query from raw text
        
        Works best for English and word-based languages.
        For CJK characters, LIKE search will be used as fallback.
        """
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
        """Convert SQLite BM25 rank to a [0, 1) relevance score.

        SQLite's bm25() returns a non-positive float (0 or negative).
        More negative = more relevant.  max(0, rank) would clip every
        negative value to 0, making every score 1/(1+0) = 1.0 and
        destroying all ranking information.

        abs(rank) / (1 + abs(rank)) maps the absolute relevance magnitude
        to [0, 1): larger |rank| (stronger match) → score closer to 1.
        """
        if rank is None:
            return 0.0
        # Add a floor of 0.3 so any FTS5 match always exceeds typical
        # min_score thresholds (default 0.1).  Small-corpus ranks close to
        # 0 would otherwise produce score≈0 and be filtered out downstream.
        return 0.3 + 0.69 * (abs(rank) / (1.0 + abs(rank)))
    
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
