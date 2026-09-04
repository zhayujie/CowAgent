"""Optional real-backend tests; install ``.[milvus-lite]`` to run them."""

import pytest

pytest.importorskip("milvus_lite")
pytest.importorskip("pymilvus")

from agent.memory.milvus_backend import MilvusVectorBackend
from agent.memory.vector_backend import VectorRecord


def item(item_id, embedding, *, scope="shared", user_id=None, path=None):
    return VectorRecord(
        id=item_id,
        embedding=embedding,
        metadata={
            "user_id": user_id,
            "scope": scope,
            "source": "memory",
            "path": path or "memory/{}.md".format(item_id),
            "start_line": 1,
            "end_line": 1,
            "text": "text for {}".format(item_id),
            "metadata": {"kind": "integration"},
        },
    )


def test_milvus_lite_crud_filter_score_and_reopen(tmp_path):
    uri = str(tmp_path / "milvus.db")
    kwargs = {
        "uri": uri,
        "collection_name": "cowagent_integration",
        "dimension": 2,
        "workspace_id": "workspace-integration",
    }
    backend = MilvusVectorBackend(**kwargs)
    backend.upsert([
        item("shared-best", [1.0, 0.0]),
        item("shared-second", [0.8, 0.2]),
        item(
            "current-user",
            [0.9, 0.1],
            scope="user",
            user_id="current",
        ),
        item(
            "other-user",
            [1.0, 0.0],
            scope="user",
            user_id="other",
        ),
    ])

    matches = backend.search(
        [1.0, 0.0],
        metadata_filter={
            "scopes": ["shared", "user"],
            "user_id": "current",
        },
        limit=10,
    )
    assert [match.id for match in matches] == [
        "shared-best",
        "current-user",
        "shared-second",
    ]
    assert all(match.score > 0 for match in matches)
    assert matches[0].metadata["metadata"] == {"kind": "integration"}

    backend.delete(metadata_filter={"path": "memory/shared-second.md"})
    backend.close()

    reopened = MilvusVectorBackend(**kwargs)
    remaining = reopened.search(
        [1.0, 0.0],
        metadata_filter={"scopes": ["shared"]},
        limit=10,
    )
    assert [match.id for match in remaining] == ["shared-best"]
    reopened.close()
