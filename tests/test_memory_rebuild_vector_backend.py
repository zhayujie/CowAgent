from types import SimpleNamespace

from agent.memory.embedding.rebuild import rebuild_in_process


class ProbeEmbeddingProvider:
    def embed_query(self, _text):
        return [1.0, 0.0]


def test_rebuild_aborts_before_clearing_when_vector_preflight_fails():
    def fail_preflight():
        raise ConnectionError("Milvus is unavailable")

    manager = SimpleNamespace(
        embedding_provider=ProbeEmbeddingProvider(),
        configure_vector_backend=fail_preflight,
    )

    result = rebuild_in_process(manager)

    assert result.ok is False
    assert result.removed == 0
    assert result.error == "vector backend preflight failed: Milvus is unavailable"
