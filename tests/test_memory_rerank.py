from agent.memory.manager import MemoryManager
from agent.memory.reranker import Reranker, _sigmoid
from agent.memory.storage import SearchResult


def _result(label):
    return SearchResult(
        path=f"memory/shared/{label}.md",
        start_line=1,
        end_line=1,
        score=0.0,
        snippet=f"snippet {label}",
        source="memory",
        user_id=None,
    )


class ScriptedReranker(Reranker):
    """Returns a fixed score per document, keyed by the snippet text."""

    def __init__(self, scores):
        self.model_name = "scripted"
        self.scores = scores

    def rerank(self, query, documents):
        return [self.scores.get(doc, 0.0) for doc in documents]


def _manager_with(reranker):
    # _rerank only touches self.reranker and a static method, so a bare
    # instance avoids opening a real MemoryStorage/embedding provider.
    manager = MemoryManager.__new__(MemoryManager)
    manager.reranker = reranker
    return manager


def test_rerank_reorders_by_cross_encoder_score():
    results = [_result("a"), _result("b"), _result("c")]
    reranker = ScriptedReranker({"snippet a": 0.1, "snippet b": 0.5, "snippet c": 0.9})

    reranked = _manager_with(reranker)._rerank("query", results)

    assert [r.snippet for r in reranked] == ["snippet c", "snippet b", "snippet a"]
    # Non-dated paths carry decay 1.0, so scores pass through unchanged.
    assert [r.score for r in reranked] == [0.9, 0.5, 0.1]


def test_rerank_is_noop_without_reranker():
    results = [_result("a"), _result("b")]

    assert _manager_with(None)._rerank("query", results) is results


def test_sigmoid_maps_to_unit_interval():
    assert _sigmoid(0.0) == 0.5
    assert 0.0 < _sigmoid(-5.0) < 0.5 < _sigmoid(5.0) < 1.0
