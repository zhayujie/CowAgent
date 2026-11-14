"""Pluggable vector storage contract for memory retrieval."""

from __future__ import annotations

import json
import math
import sqlite3
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    np = None  # type: ignore[assignment]


@dataclass
class VectorRecord:
    """A vector and the metadata needed to reconstruct a memory result."""

    id: str
    embedding: Optional[List[float]]
    metadata: Dict[str, Any]


@dataclass
class VectorMatch:
    """A scored vector match returned by a backend."""

    id: str
    score: float
    metadata: Dict[str, Any]


class VectorBackend(ABC):
    """Storage-independent vector operations used by memory."""

    @abstractmethod
    def upsert(self, records: Sequence[VectorRecord]) -> None:
        """Insert or update vector records."""

    @abstractmethod
    def delete(
        self,
        ids: Optional[Sequence[str]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Delete vectors by IDs and/or metadata."""

    @abstractmethod
    def search(
        self,
        query_embedding: Sequence[float],
        limit: int = 10,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[VectorMatch]:
        """Return the highest-scoring matches satisfying the filter."""


class SQLiteVectorBackend(VectorBackend):
    """Vector backend backed by the existing ``chunks.embedding`` column.

    The owning ``MemoryStorage`` controls locking and transaction boundaries,
    so writes intentionally do not commit here.
    """

    _FILTER_COLUMNS = {"id", "user_id", "scope", "source", "path"}

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        self.connection.executemany(
            "UPDATE chunks SET embedding = ? WHERE id = ?",
            [
                (self._encode_embedding(record.embedding), record.id)
                for record in records
            ],
        )

    def delete(
        self,
        ids: Optional[Sequence[str]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        clauses, params = self._build_filter(metadata_filter)
        if ids is not None:
            if not ids:
                return
            clauses.append("id IN ({})".format(",".join("?" for _ in ids)))
            params.extend(ids)
        if not clauses:
            raise ValueError("Vector deletion requires IDs or a metadata filter")
        self.connection.execute(
            "UPDATE chunks SET embedding = NULL WHERE " + " AND ".join(clauses),
            params,
        )

    def search(
        self,
        query_embedding: Sequence[float],
        limit: int = 10,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[VectorMatch]:
        if limit <= 0 or not query_embedding:
            return []

        clauses, params = self._build_filter(
            metadata_filter,
            shared_visible_to_user=True,
        )
        clauses.append("embedding IS NOT NULL")
        rows = self.connection.execute(
            "SELECT * FROM chunks WHERE " + " AND ".join(clauses),
            params,
        ).fetchall()
        if not rows:
            return []

        expected_dim = len(query_embedding)
        valid_rows = []
        vectors = []
        for row in rows:
            try:
                vector = self._decode_finite_vector(row["embedding"])
            except (ValueError, TypeError, OverflowError, struct.error) as exc:
                from common.log import logger

                logger.warning("[SQLiteVectorBackend] Skipping malformed embedding for chunk %s: %s", row["id"], exc)
                continue
            if len(vector) == 0:
                continue
            if len(vector) != expected_dim:
                from common.log import logger

                logger.warning(
                    "[SQLiteVectorBackend] Skipping chunk %s: "
                    "embedding dim %d != query dim %d",
                    row["id"],
                    len(vector),
                    expected_dim,
                )
                continue
            valid_rows.append(row)
            vectors.append(vector)

        if not vectors:
            return []

        if _HAS_NUMPY:
            scores = self._numpy_scores(vectors, query_embedding)
            count = min(limit, len(valid_rows))
            top_indices = np.argpartition(scores, -count)[-count:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
            return [
                self._match(valid_rows[index], float(scores[index]))
                for index in top_indices
                if scores[index] > 0
            ]

        query_norm = math.sqrt(sum(value * value for value in query_embedding)) or 1e-10
        scored = []
        for row, vector in zip(valid_rows, vectors):
            dot = sum(left * right for left, right in zip(vector, query_embedding))
            vector_norm = math.sqrt(sum(value * value for value in vector)) or 1e-10
            score = dot / (vector_norm * query_norm)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [self._match(row, score) for score, row in scored[:limit]]

    @staticmethod
    def _numpy_scores(vectors, query_embedding):
        matrix = np.array(vectors, dtype=np.float32)
        query = np.array(query_embedding, dtype=np.float32)
        dots = matrix @ query
        denominators = np.linalg.norm(matrix, axis=1) * float(np.linalg.norm(query))
        np.maximum(denominators, 1e-10, out=denominators)
        return dots / denominators

    @classmethod
    def _build_filter(cls, metadata_filter, shared_visible_to_user=False):
        clauses = []
        params = []
        metadata_filter = metadata_filter or {}

        scopes = metadata_filter.get("scopes")
        if scopes is not None:
            if not scopes:
                clauses.append("0")
            else:
                clauses.append(
                    "scope IN ({})".format(",".join("?" for _ in scopes))
                )
                params.extend(scopes)

        user_id = metadata_filter.get("user_id")
        if shared_visible_to_user and user_id:
            clauses.append("(scope = 'shared' OR user_id = ?)")
            params.append(user_id)

        for key, value in metadata_filter.items():
            if key == "scopes" or (
                key == "user_id" and shared_visible_to_user
            ) or value is None:
                continue
            if key not in cls._FILTER_COLUMNS:
                raise ValueError("Unsupported vector metadata filter: {}".format(key))
            clauses.append("{} = ?".format(key))
            params.append(value)
        return clauses, params

    @staticmethod
    def _match(row, score: float) -> VectorMatch:
        return VectorMatch(
            id=row["id"],
            score=score,
            metadata={
                "user_id": row["user_id"],
                "scope": row["scope"],
                "source": row["source"],
                "path": row["path"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "text": row["text"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
            },
        )

    @staticmethod
    def _encode_embedding(embedding: Optional[Sequence[float]]) -> Optional[bytes]:
        if embedding is None:
            return None
        if _HAS_NUMPY:
            return np.array(embedding, dtype=np.float32).tobytes()
        return struct.pack("{}f".format(len(embedding)), *embedding)

    @classmethod
    def _decode_finite_vector(cls, raw):
        """Decode a stored embedding for scoring; raise ValueError on NaN or inf.

        Blobs are checked as NumPy arrays: converting every value to a Python
        float first took most of the search time on a large index.
        """
        if _HAS_NUMPY and isinstance(raw, (bytes, bytearray)):
            vector = np.frombuffer(raw, dtype=np.float32)
            if not np.isfinite(vector).all():
                raise ValueError("embedding contains nonfinite values")
            return vector
        decoded = cls._decode_embedding(raw)
        vector = [float(value) for value in decoded] if decoded else []
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("embedding contains nonfinite values")
        return vector

    @staticmethod
    def _decode_embedding(raw) -> Optional[List[float]]:
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            if _HAS_NUMPY:
                return np.frombuffer(raw, dtype=np.float32).tolist()
            count = len(raw) // 4
            return list(struct.unpack("{}f".format(count), raw))
        return json.loads(raw)
