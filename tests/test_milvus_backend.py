import pytest

from agent.memory.config import MemoryConfig, create_memory_config
from agent.memory.milvus_backend import (
    MilvusConfigurationError,
    MilvusVectorBackend,
)
from agent.memory.vector_backend import VectorRecord
from agent.memory.vector_backend_factory import create_external_vector_backend


class FakeDataType:
    VARCHAR = "VARCHAR"
    FLOAT_VECTOR = "FLOAT_VECTOR"
    INT64 = "INT64"


class FakeSchema:
    def __init__(self):
        self.fields = []

    def add_field(self, **kwargs):
        field = {"name": kwargs["field_name"], "params": {}}
        if "dim" in kwargs:
            field["params"]["dim"] = kwargs["dim"]
        self.fields.append(field)


class FakeIndexParams:
    def __init__(self):
        self.indexes = []

    def add_index(self, **kwargs):
        self.indexes.append(kwargs)


class FakeMilvusClient:
    def __init__(self, *, existing=False, dimension=2, **kwargs):
        self.kwargs = kwargs
        self.existing = existing
        self.dimension = dimension
        self.schema = None
        self.index_params = None
        self.loaded = []
        self.upserts = []
        self.deletes = []
        self.search_kwargs = None
        self.search_response = [[]]
        self.closed = False

    def has_collection(self, **kwargs):
        return self.existing

    def create_schema(self, **kwargs):
        return FakeSchema()

    def prepare_index_params(self):
        return FakeIndexParams()

    def create_collection(self, **kwargs):
        self.existing = True
        self.schema = kwargs["schema"]
        self.index_params = kwargs["index_params"]

    def describe_collection(self, **kwargs):
        names = [
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
        ]
        return {
            "fields": [
                {
                    "name": name,
                    "params": {"dim": self.dimension}
                    if name == "embedding"
                    else {},
                }
                for name in names
            ]
        }

    def describe_index(self, **kwargs):
        return {"metric_type": "COSINE"}

    def load_collection(self, **kwargs):
        self.loaded.append(kwargs["collection_name"])

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def delete(self, **kwargs):
        self.deletes.append(kwargs)

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        return self.search_response

    def close(self):
        self.closed = True


def backend_with(client):
    return MilvusVectorBackend(
        uri="http://milvus.invalid:19530",
        collection_name="cowagent_test",
        dimension=2,
        workspace_id="workspace-a",
        token="secret-token",
        client_factory=lambda **kwargs: client,
        data_type=FakeDataType,
    )


def record(record_id="chunk-1", embedding=None, **metadata):
    values = {
        "user_id": None,
        "scope": "shared",
        "source": "memory",
        "path": "memory/test.md",
        "start_line": 1,
        "end_line": 2,
        "text": "hello",
        "metadata": {"kind": "note"},
    }
    values.update(metadata)
    return VectorRecord(
        id=record_id,
        embedding=embedding if embedding is not None else [1.0, 0.0],
        metadata=values,
    )


def test_milvus_backend_creates_schema_upserts_and_loads_collection():
    client = FakeMilvusClient()
    backend = backend_with(client)

    backend.upsert([record()])

    assert client.loaded == ["cowagent_test"]
    assert {field["name"] for field in client.schema.fields} >= {
        "id",
        "embedding",
        "workspace_id",
        "scope",
        "path",
        "text",
    }
    assert client.index_params.indexes == [
        {
            "field_name": "embedding",
            "index_name": "embedding",
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
        }
    ]
    assert client.upserts[0]["data"][0]["workspace_id"] == "workspace-a"
    assert client.upserts[0]["data"][0]["metadata_json"] == '{"kind":"note"}'


def test_milvus_backend_preserves_visibility_filters_and_score_order():
    client = FakeMilvusClient(existing=True)
    client.search_response = [[
        {
            "id": "second",
            "distance": 0.5,
            "entity": {
                "user_id": "",
                "scope": "shared",
                "source": "memory",
                "path": "second.md",
                "start_line": 1,
                "end_line": 1,
                "text": "second",
                "metadata_json": "null",
            },
        },
        {
            "id": "best",
            "distance": 0.9,
            "entity": {
                "user_id": "current",
                "scope": "user",
                "source": "knowledge",
                "path": "best.md",
                "start_line": 2,
                "end_line": 3,
                "text": "best",
                "metadata_json": '{"kind":"doc"}',
            },
        },
        {"id": "negative", "distance": -0.1, "entity": {}},
    ]]
    backend = backend_with(client)

    matches = backend.search(
        [1.0, 0.0],
        metadata_filter={
            "scopes": ["shared", "user"],
            "user_id": "current",
            "source": "memory",
        },
    )

    expression = client.search_kwargs["filter"]
    assert 'workspace_id == "workspace-a"' in expression
    assert 'scope in ["shared","user"]' in expression
    assert '(scope == "shared" or user_id == "current")' in expression
    assert 'source == "memory"' in expression
    assert [match.id for match in matches] == ["best", "second"]
    assert matches[0].metadata["metadata"] == {"kind": "doc"}


def test_milvus_filter_literals_escape_untrusted_values():
    client = FakeMilvusClient(existing=True)
    backend = backend_with(client)

    backend.delete(metadata_filter={"path": 'a" or workspace_id != "x\\y'})

    expression = client.deletes[0]["filter"]
    assert expression.startswith('workspace_id == "workspace-a" and path == ')
    assert '\\" or workspace_id != \\"x\\\\y' in expression


def test_milvus_backend_rejects_existing_dimension_mismatch():
    client = FakeMilvusClient(existing=True, dimension=3)
    backend = backend_with(client)

    with pytest.raises(MilvusConfigurationError, match="dimension 3"):
        backend.prepare()


def test_milvus_none_embedding_deletes_stale_vector():
    client = FakeMilvusClient(existing=True)
    backend = backend_with(client)
    item = record(embedding=[1.0, 0.0])
    item.embedding = None

    backend.upsert([item])

    assert client.upserts == []
    assert 'id in ["chunk-1"]' in client.deletes[0]["filter"]


def test_vector_backend_factory_keeps_sqlite_default_and_scopes_milvus(tmp_path):
    sqlite_config = MemoryConfig(workspace_root=str(tmp_path))
    assert create_external_vector_backend(sqlite_config, 2) is None

    milvus_config = MemoryConfig(
        workspace_root=str(tmp_path),
        vector_backend="milvus",
    )
    backend = create_external_vector_backend(milvus_config, 2)
    assert isinstance(backend, MilvusVectorBackend)
    assert backend.collection_name.startswith("cowagent_memory_")
    assert backend.collection_name.endswith("_d2")
    assert backend.uri.endswith("milvus.db")


def test_vector_backend_factory_prefers_environment_token(tmp_path, monkeypatch):
    monkeypatch.setenv("MILVUS_TOKEN", "environment-token")
    config = MemoryConfig(
        workspace_root=str(tmp_path),
        vector_backend="milvus",
        milvus_token="file-token",
    )

    backend = create_external_vector_backend(config, 2)

    assert backend.token == "environment-token"


def test_create_memory_config_reads_optional_backend_settings(tmp_path, monkeypatch):
    runtime = {
        "vector_backend": "milvus",
        "milvus_uri": "http://localhost:19530",
        "milvus_token": "configured-token",
        "milvus_db_name": "cowagent",
        "milvus_collection": "memory_vectors",
        "milvus_timeout": 3.5,
        "milvus_consistency_level": "Bounded",
    }
    monkeypatch.setattr("config.conf", lambda: runtime)

    config = create_memory_config(str(tmp_path))

    assert config.vector_backend == "milvus"
    assert config.milvus_uri == "http://localhost:19530"
    assert config.milvus_token == "configured-token"
    assert config.milvus_db_name == "cowagent"
    assert config.milvus_collection == "memory_vectors"
    assert config.milvus_timeout == 3.5
    assert config.milvus_consistency_level == "Bounded"


def test_config_diagnostics_redact_milvus_credentials():
    from config import drag_sensitive

    masked = drag_sensitive({
        "milvus_token": "short",
        "web_password": "also-secret",
        "milvus_uri": "https://milvus.example.com",
    })

    assert masked["milvus_token"] == "<redacted>"
    assert masked["web_password"] == "<redacted>"
    assert masked["milvus_uri"] == "<redacted>"
