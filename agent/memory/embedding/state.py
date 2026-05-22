"""
Embedding-related index utilities.

We don't keep a sidecar state file — the SQLite index is the source of truth
and config.json is the source of intent. The two functions below are the
only things needing on-disk awareness:

  detect_index_dim         : read the dim of stored vectors (display-only)
  cleanup_legacy_state_file: remove old embedding_state.json from earlier
                             versions; safe no-op when absent.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, os.PathLike]


def detect_index_dim(storage) -> Optional[int]:
    """Return the dim of the first stored embedding, or None if the index
    has no embeddings. Used by /memory status."""
    try:
        row = storage.conn.execute(
            "SELECT embedding FROM chunks WHERE embedding IS NOT NULL LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    if not row or not row["embedding"]:
        return None
    try:
        emb = json.loads(row["embedding"])
        return len(emb) if isinstance(emb, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def cleanup_legacy_state_file(db_path: PathLike) -> None:
    """Remove old embedding_state.json files from earlier versions.
    Safe to call repeatedly; no-op if the file is absent."""
    legacy = Path(db_path).parent / "embedding_state.json"
    try:
        legacy.unlink(missing_ok=True)
    except Exception:
        pass
