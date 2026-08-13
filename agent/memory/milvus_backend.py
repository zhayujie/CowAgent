"""Optional Milvus implementation of the memory vector backend contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Sequence

from agent.memory.vector_backend import VectorBackend, VectorMatch, VectorRecord


class MilvusConfigurationError(ValueError):
    """Raised when an existing collection is incompatible with CowAgent."""


class MilvusVectorBackend(VectorBackend):
    """Store and search memory vectors through ``pymilvus.MilvusClient``.

    PyMilvus is imported lazily so the default SQLite backend stays completely
    dependency-free.  A client factory and DataType object can be injected by
    unit tests without importing the optional package.
    """

    _FILTER_COLUMNS = {"id", "user_id", "scope", "source", "path"}
    _OUTPUT_FIELDS = [
        "user_id",
        "scope",
        "source",
        "path",
        "start_line",
        "end_line",
        "text",
        "metadata_json",
    ]

    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        dimension: int,
        workspace_id: str,
        token: str = "",
        db_name: str = "default",
        timeout: float = 10.0,
        consistency_level: str = "Strong",
        client_factory: Optional[Callable[..., Any]] = None,
        data_type: Any = None,
    ):
        if dimension <= 1:
            raise MilvusConfigurationError(
                "Milvus requires an embedding dimension greater than 1"
            )
        if not uri:
            raise MilvusConfigurationError("Milvus URI cannot be empty")
        if not collection_name:
            raise MilvusConfigurationError("Milvus collection name cannot be empty")

        self.uri = uri
        self.collection_name = collection_name
        self.dimension = int(dimension)
        self.workspace_id = workspace_id
        self.token = token
        self.db_name = db_name or "default"
        self.timeout = float(timeout)
        self.consistency_level = consistency_level or "Strong"
        self._client_factory = client_factory
        self._data_type = data_type
        self._client = None
        self._ready = False
        self.collection_created = False

    @property
    def backend_name(self) -> str:
        return "milvus"

    @property
    def sync_key(self) -> str:
        raw = "{}:{}:{}".format(
            self.collection_name,
            self.workspace_id,
            self.dimension,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def prepare(self) -> bool:
        """Ensure the collection is usable and report whether it was created."""
        self._ensure_ready()
        created = self.collection_created
        self.collection_created = False
        return created

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        self._ensure_ready()

        rows = []
        missing_ids = []
        for record in records:
            if record.embedding is None:
                missing_ids.append(record.id)
                continue
            self._validate_dimension(record.embedding)
            metadata = record.metadata
            rows.append(
                {
                    "id": record.id,
                    "embedding": list(record.embedding),
                    "workspace_id": self.workspace_id,
                    "user_id": metadata.get("user_id") or "",
                    "scope": metadata.get("scope") or "shared",
                    "source": metadata.get("source") or "memory",
                    "path": metadata.get("path") or "",
                    "start_line": int(metadata.get("start_line") or 0),
                    "end_line": int(metadata.get("end_line") or 0),
                    "text": metadata.get("text") or "",
                    "metadata_json": json.dumps(
                        metadata.get("metadata"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )

        if rows:
            self._client.upsert(
                collection_name=self.collection_name,
                data=rows,
                timeout=self.timeout,
            )
        if missing_ids:
            self.delete(ids=missing_ids)

    def delete(
        self,
        ids: Optional[Sequence[str]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        if ids is not None and not ids:
            return
        if ids is None and not metadata_filter:
            raise ValueError("Vector deletion requires IDs or a metadata filter")

        self._ensure_ready()
        expression = self._build_filter(
            metadata_filter,
            ids=ids,
            shared_visible_to_user=False,
        )
        self._client.delete(
            collection_name=self.collection_name,
            filter=expression,
            timeout=self.timeout,
        )

    def search(
        self,
        query_embedding: Sequence[float],
        limit: int = 10,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[VectorMatch]:
        if limit <= 0 or not query_embedding:
            return []
        self._validate_dimension(query_embedding)
        self._ensure_ready()

        expression = self._build_filter(
            metadata_filter,
            shared_visible_to_user=True,
        )
        response = self._client.search(
            collection_name=self.collection_name,
            data=[list(query_embedding)],
            anns_field="embedding",
            filter=expression,
            limit=limit,
            output_fields=self._OUTPUT_FIELDS,
            search_params={"metric_type": "COSINE", "params": {}},
            consistency_level=self.consistency_level,
            timeout=self.timeout,
        )

        hits = response[0] if response else []
        matches = []
        for hit in hits:
            score = float(hit.get("distance", hit.get("score", 0.0)))
            if score <= 0:
                continue
            entity = hit.get("entity") or {}
            raw_metadata = entity.get("metadata_json")
            try:
                metadata = json.loads(raw_metadata) if raw_metadata else None
            except (TypeError, ValueError):
                metadata = None
            matches.append(
                VectorMatch(
                    id=str(hit.get("id", entity.get("id", ""))),
                    score=score,
                    metadata={
                        "user_id": entity.get("user_id") or None,
                        "scope": entity.get("scope"),
                        "source": entity.get("source"),
                        "path": entity.get("path"),
                        "start_line": entity.get("start_line"),
                        "end_line": entity.get("end_line"),
                        "text": entity.get("text") or "",
                        "metadata": metadata,
                    },
                )
            )
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]

    def close(self) -> None:
        client = self._client
        self._client = None
        self._ready = False
        if client is not None:
            client.close()

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        if self._client is None:
            self._client = self._create_client()

        if self._client.has_collection(
            collection_name=self.collection_name,
            timeout=self.timeout,
        ):
            self.collection_created = False
            self._validate_collection()
        else:
            self._create_collection()
            self.collection_created = True

        # Existing Lite collections are released after the previous client is
        # closed. Loading is idempotent for server and cloud deployments.
        self._client.load_collection(
            collection_name=self.collection_name,
            timeout=self.timeout,
        )
        self._ready = True

    def _create_client(self):
        factory = self._client_factory
        if factory is None:
            try:
                from pymilvus import DataType, MilvusClient
            except ImportError as exc:
                raise RuntimeError(
                    "Milvus backend requires the optional 'milvus' extra"
                ) from exc
            factory = MilvusClient
            self._data_type = DataType

        kwargs = {
            "uri": self.uri,
            "db_name": self.db_name,
            "timeout": self.timeout,
        }
        if self.token:
            kwargs["token"] = self.token
        return factory(**kwargs)

    def _create_collection(self) -> None:
        data_type = self._data_type
        if data_type is None:
            raise RuntimeError("Milvus DataType is unavailable")

        schema = self._client.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
        )
        schema.add_field(
            field_name="id",
            datatype=data_type.VARCHAR,
            is_primary=True,
            max_length=64,
        )
        schema.add_field(
            field_name="embedding",
            datatype=data_type.FLOAT_VECTOR,
            dim=self.dimension,
        )
        for name, max_length in (
            ("workspace_id", 64),
            ("user_id", 4096),
            ("scope", 64),
            ("source", 256),
            ("path", 65535),
            ("text", 65535),
            ("metadata_json", 65535),
        ):
            schema.add_field(
                field_name=name,
                datatype=data_type.VARCHAR,
                max_length=max_length,
            )
        schema.add_field(field_name="start_line", datatype=data_type.INT64)
        schema.add_field(field_name="end_line", datatype=data_type.INT64)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level=self.consistency_level,
            timeout=self.timeout,
        )

    def _validate_collection(self) -> None:
        description = self._client.describe_collection(
            collection_name=self.collection_name,
            timeout=self.timeout,
        )
        fields = {
            field.get("name"): field
            for field in (description.get("fields") or [])
        }
        required = {
            "id",
            "embedding",
            "workspace_id",
            "user_id",
            "scope",
            "source",
            "path",
            "start_line",
            "end_line",
            "text",
            "metadata_json",
        }
        missing = sorted(required.difference(fields))
        if missing:
            raise MilvusConfigurationError(
                "Milvus collection '{}' is missing required fields: {}".format(
                    self.collection_name,
                    ", ".join(missing),
                )
            )

        vector_params = fields["embedding"].get("params") or {}
        actual_dimension = int(vector_params.get("dim") or 0)
        if actual_dimension != self.dimension:
            raise MilvusConfigurationError(
                "Milvus collection '{}' dimension {} does not match embedding "
                "dimension {}".format(
                    self.collection_name,
                    actual_dimension,
                    self.dimension,
                )
            )

        try:
            index = self._client.describe_index(
                collection_name=self.collection_name,
                index_name="embedding",
                timeout=self.timeout,
            )
        except Exception:
            # Older compatible servers may not expose describe_index through
            # MilvusClient. Search still supplies COSINE explicitly.
            return
        metric = str(index.get("metric_type") or "").upper()
        if metric and metric != "COSINE":
            raise MilvusConfigurationError(
                "Milvus collection '{}' uses {} instead of COSINE".format(
                    self.collection_name,
                    metric,
                )
            )

    def _validate_dimension(self, embedding: Sequence[float]) -> None:
        if len(embedding) != self.dimension:
            raise MilvusConfigurationError(
                "Embedding dimension {} does not match Milvus dimension {}".format(
                    len(embedding),
                    self.dimension,
                )
            )

    def _build_filter(
        self,
        metadata_filter: Optional[Dict[str, Any]],
        *,
        ids: Optional[Sequence[str]] = None,
        shared_visible_to_user: bool,
    ) -> str:
        clauses = ["workspace_id == {}".format(self._literal(self.workspace_id))]
        metadata_filter = metadata_filter or {}

        scopes = metadata_filter.get("scopes")
        if scopes is not None:
            if not scopes:
                clauses.append("id == {}".format(self._literal("__no_match__")))
            else:
                clauses.append("scope in {}".format(self._literal(list(scopes))))

        user_id = metadata_filter.get("user_id")
        if shared_visible_to_user and user_id:
            clauses.append(
                "(scope == {} or user_id == {})".format(
                    self._literal("shared"),
                    self._literal(user_id),
                )
            )

        for key, value in metadata_filter.items():
            if key == "scopes" or (
                key == "user_id" and shared_visible_to_user
            ) or value is None:
                continue
            if key not in self._FILTER_COLUMNS:
                raise ValueError(
                    "Unsupported vector metadata filter: {}".format(key)
                )
            clauses.append("{} == {}".format(key, self._literal(value)))

        if ids is not None:
            clauses.append("id in {}".format(self._literal(list(ids))))
        return " and ".join(clauses)

    @staticmethod
    def _literal(value: Any) -> str:
        """Encode values without interpolating raw user-controlled syntax."""
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
