from agent.memory.storage import MemoryChunk, MemoryStorage
from agent.memory.vector_backend import (
    SQLiteVectorBackend,
    VectorBackend,
    VectorMatch,
    VectorRecord,
)


def _chunk(
    chunk_id,
    embedding,
    *,
    path="memory/shared/test.md",
    scope="shared",
    user_id=None,
):
    return MemoryChunk(
        id=chunk_id,
        user_id=user_id,
        scope=scope,
        source="memory",
        path=path,
        start_line=1,
        end_line=1,
        text=f"text for {chunk_id}",
        embedding=embedding,
        hash=f"hash-{chunk_id}",
        metadata={"kind": "note"},
    )


def test_sqlite_vector_backend_preserves_filtering_and_score_order(tmp_path):
    storage = MemoryStorage(tmp_path / "index.db")
    assert isinstance(storage.vector_backend, SQLiteVectorBackend)
    storage.save_chunks_batch(
        [
            _chunk("shared-best", [1.0, 0.0]),
            _chunk("shared-second", [0.8, 0.2]),
            _chunk(
                "other-user",
                [1.0, 0.0],
                path="memory/users/other/test.md",
                scope="user",
                user_id="other",
            ),
        ]
    )

    results = storage.search_vector(
        [1.0, 0.0],
        user_id="current",
        scopes=["shared", "user"],
        limit=10,
    )

    assert [result.path for result in results] == [
        "memory/shared/test.md",
        "memory/shared/test.md",
    ]
    assert results[0].score > results[1].score
    assert storage.get_chunk("shared-best").embedding == [1.0, 0.0]
    storage.close()


class RecordingVectorBackend(VectorBackend):
    def __init__(self):
        self.upserted = []
        self.deleted = []
        self.search_filter = None

    def upsert(self, records):
        self.upserted.extend(records)

    def delete(self, ids=None, metadata_filter=None):
        self.deleted.append((ids, metadata_filter))

    def search(self, query_embedding, limit=10, metadata_filter=None):
        self.search_filter = metadata_filter
        return [
            VectorMatch(
                id="custom-result",
                score=0.75,
                metadata={
                    "path": "memory/shared/custom.md",
                    "start_line": 3,
                    "end_line": 4,
                    "text": "custom backend text",
                    "source": "memory",
                    "user_id": None,
                },
            )
        ]


def test_memory_storage_routes_vector_operations_through_backend(tmp_path):
    backend = RecordingVectorBackend()
    storage = MemoryStorage(tmp_path / "index.db", vector_backend=backend)
    chunk = _chunk("custom-result", [0.5, 0.5], path="memory/shared/custom.md")

    storage.save_chunk(chunk)
    results = storage.search_vector(
        [0.5, 0.5],
        user_id="current",
        scopes=["shared", "user"],
        limit=4,
    )
    storage.delete_by_path(chunk.path)

    assert backend.upserted == [
        VectorRecord(
            id="custom-result",
            embedding=[0.5, 0.5],
            metadata={
                "user_id": None,
                "scope": "shared",
                "source": "memory",
                "path": "memory/shared/custom.md",
                "start_line": 1,
                "end_line": 1,
                "text": "text for custom-result",
                "metadata": {"kind": "note"},
            },
        )
    ]
    assert backend.search_filter == {
        "scopes": ["shared", "user"],
        "user_id": "current",
    }
    assert backend.deleted == [(None, {"path": "memory/shared/custom.md"})]
    assert results[0].path == "memory/shared/custom.md"
    assert results[0].score == 0.75
    storage.close()


class FailingVectorBackend(RecordingVectorBackend):
    def __init__(self):
        super().__init__()
        self.fail_writes = True
        self.fail_deletes = False
        self.token = "top-secret-token"
        self.uri = "https://user:password@milvus.example.com"

    def upsert(self, records):
        if self.fail_writes:
            raise ConnectionError(
                "{} at {} is unavailable".format(self.token, self.uri)
            )
        super().upsert(records)

    def delete(self, ids=None, metadata_filter=None):
        if self.fail_deletes:
            raise ConnectionError("delete failed at {}".format(self.uri))
        super().delete(ids=ids, metadata_filter=metadata_filter)


def test_external_failure_keeps_sqlite_vectors_and_pending_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.memory.storage.time.sleep", lambda _seconds: None)
    backend = FailingVectorBackend()
    storage = MemoryStorage(tmp_path / "index.db", vector_backend=backend)
    chunk = _chunk("durable", [1.0, 0.0])

    storage.save_chunk(chunk)

    assert storage.get_chunk("durable").embedding == [1.0, 0.0]
    assert storage.get_stats()["vector_sync_pending"] == 1
    results = storage.search_vector([1.0, 0.0])
    assert [result.path for result in results] == [chunk.path]
    status = storage.get_vector_backend_status()
    assert status["healthy"] is False
    assert "top-secret-token" not in status["error"]
    assert "password" not in status["error"]

    backend.fail_writes = False
    results = storage.search_vector([1.0, 0.0])
    assert storage.get_stats()["vector_sync_pending"] == 0
    assert backend.upserted[0].id == "durable"
    assert results[0].score == 0.75
    storage.close()


def test_external_delete_failure_is_durable_and_retried(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.memory.storage.time.sleep", lambda _seconds: None)
    backend = FailingVectorBackend()
    backend.fail_writes = False
    storage = MemoryStorage(tmp_path / "index.db", vector_backend=backend)
    chunk = _chunk("delete-me", [1.0, 0.0])
    storage.save_chunk(chunk)

    backend.fail_deletes = True
    storage.delete_by_path(chunk.path)

    assert storage.get_chunk(chunk.id) is None
    assert storage.get_stats()["vector_sync_pending"] == 1
    backend.fail_deletes = False
    storage.search_vector([1.0, 0.0])
    assert storage.get_stats()["vector_sync_pending"] == 0
    assert backend.deleted[-1] == ([chunk.id], None)
    storage.close()


def test_existing_sqlite_vectors_are_backfilled_once(tmp_path):
    db_path = tmp_path / "index.db"
    sqlite_storage = MemoryStorage(db_path)
    sqlite_storage.save_chunk(_chunk("legacy", [0.5, 0.5]))
    sqlite_storage.close()

    first_backend = RecordingVectorBackend()
    storage = MemoryStorage(db_path, vector_backend=first_backend)
    assert [record.id for record in first_backend.upserted] == ["legacy"]
    storage.close()

    second_backend = RecordingVectorBackend()
    storage = MemoryStorage(db_path, vector_backend=second_backend)
    assert second_backend.upserted == []
    storage.close()


class ConcurrentUpdateBackend(RecordingVectorBackend):
    def __init__(self):
        super().__init__()
        self.storage = None
        self.calls = 0

    def upsert(self, records):
        self.calls += 1
        super().upsert(records)
        if self.calls == 1:
            self.storage._enqueue_vector_upserts(records)
            self.storage.conn.commit()


def test_vector_queue_does_not_lose_update_during_remote_call(tmp_path):
    backend = ConcurrentUpdateBackend()
    storage = MemoryStorage(tmp_path / "index.db", vector_backend=backend)
    backend.storage = storage

    storage.save_chunk(_chunk("concurrent", [1.0, 0.0]))

    assert backend.calls == 2
    assert storage.get_stats()["vector_sync_pending"] == 0
    storage.close()
