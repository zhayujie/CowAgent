from agent.memory.manager import MemoryManager
from agent.memory.storage import SearchResult


def _result(label, score):
    """Build a SearchResult keyed by a distinct path so each is a unique chunk."""
    return SearchResult(
        path=f"memory/shared/{label}.md",
        start_line=1,
        end_line=1,
        score=score,
        snippet=f"snippet {label}",
        source="memory",
        user_id=None,
    )


def _merge(vector_results, keyword_results, vector_weight=0.7, keyword_weight=0.3):
    # _merge_results only touches static methods, so a bare instance is enough
    # and avoids opening a real MemoryStorage/embedding provider.
    manager = MemoryManager.__new__(MemoryManager)
    return manager._merge_results(vector_results, keyword_results, vector_weight, keyword_weight)


def test_single_channel_hit_is_not_diluted():
    # A chunk returned by only the vector channel must keep its full
    # rank-normalized score (1.0), not be scaled down by keyword_weight.
    merged = _merge([_result("a", 0.9)], [])
    assert len(merged) == 1
    assert merged[0].score == 1.0


def test_fusion_is_invariant_to_score_scale():
    # Rank normalization depends on order, not magnitude: scaling keyword
    # scores by 10x must not change the merged ranking or scores.
    vector = [_result("v1", 0.9), _result("v2", 0.5)]
    keyword_low = [_result("k1", 0.4)]
    keyword_high = [_result("k1", 4.0)]

    low = _merge(vector, keyword_low)
    high = _merge(vector, keyword_high)

    assert [r.path for r in low] == [r.path for r in high]
    assert [r.score for r in low] == [r.score for r in high]


def test_weight_validation_and_degradation():
    # Negative weights are clamped to 0; an all-zero (or non-numeric) pair
    # falls back to equal weighting instead of yielding a meaningless score.
    assert MemoryManager._normalize_weights(-0.5, 0.3) == (0.0, 0.3)
    assert MemoryManager._normalize_weights(0.7, 0.0) == (0.7, 0.0)
    assert MemoryManager._normalize_weights(0.0, 0.0) == (0.5, 0.5)
    assert MemoryManager._normalize_weights(-1.0, -2.0) == (0.5, 0.5)
    assert MemoryManager._normalize_weights("x", "y") == (0.5, 0.5)

    # A bad weight config must not produce negative scores or crash.
    merged = _merge([_result("a", 0.9)], [], vector_weight=-1.0, keyword_weight=-1.0)
    assert all(r.score >= 0.0 for r in merged)
