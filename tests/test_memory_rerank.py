import asyncio
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.memory import reranker as reranker_module
from agent.memory.manager import MemoryManager
from agent.memory.reranker import (
    Reranker,
    SentenceTransformerReranker,
    _sigmoid,
    clear_reranker_cache,
    create_reranker,
    register_reranker_provider,
)
from agent.memory.storage import SearchResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def _result(label, score=0.0):
    return SearchResult(
        path=f"memory/shared/{label}.md",
        start_line=1,
        end_line=1,
        score=score,
        snippet=f"snippet {label}",
        source="memory",
        user_id=None,
    )


class ScriptedReranker(Reranker):
    """Returns a fixed score per document, keyed by the snippet text."""

    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def rerank(self, query, documents):
        self.calls.append(list(documents))
        return [self.scores.get(doc, 0.0) for doc in documents]


class FailingReranker(Reranker):
    def __init__(self, scores=None):
        self.scores = scores

    def rerank(self, query, documents):
        if self.scores is None:
            raise RuntimeError("model unavailable")
        return self.scores


def _manager_with(reranker):
    # _rerank only touches self.reranker and a static method, so a bare
    # instance avoids opening a real MemoryStorage/embedding provider.
    manager = MemoryManager.__new__(MemoryManager)
    manager.reranker = reranker
    return manager


@pytest.fixture(autouse=True)
def _isolated_reranker_cache():
    clear_reranker_cache()
    yield
    clear_reranker_cache()


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    """Stand-in for sentence_transformers that counts model loads."""
    state = SimpleNamespace(loads=0, fail=False)

    class CrossEncoder:
        def __init__(self, model_name):
            state.loads += 1
            if state.fail:
                raise OSError("cannot download model")
            self.model_name = model_name

        def predict(self, pairs):
            return [float(len(doc)) for _, doc in pairs]

    module = types.ModuleType("sentence_transformers")
    module.CrossEncoder = CrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return state


def test_rerank_reorders_by_reranker_score():
    results = [_result("a"), _result("b"), _result("c")]
    reranker = ScriptedReranker({"snippet a": 0.1, "snippet b": 0.5, "snippet c": 0.9})

    reranked = _manager_with(reranker)._rerank("query", results)

    assert [r.snippet for r in reranked] == ["snippet c", "snippet b", "snippet a"]
    # Non-dated paths carry decay 1.0, so scores pass through unchanged.
    assert [r.score for r in reranked] == [0.9, 0.5, 0.1]


def test_rerank_is_noop_without_reranker():
    results = [_result("a"), _result("b")]

    assert _manager_with(None)._rerank("query", results) is results


@pytest.mark.parametrize("reranker", [FailingReranker(), FailingReranker(scores=[0.9])])
def test_rerank_failure_keeps_fused_order(reranker):
    results = [_result("a"), _result("b")]

    assert _manager_with(reranker)._rerank("query", results) is results


def test_search_applies_min_score_before_rerank():
    keyword_hits = [_result(label) for label in ("a", "b", "c", "d")]
    reranker = ScriptedReranker(
        {"snippet a": 0.1, "snippet b": 0.5, "snippet c": 0.9, "snippet d": 0.99}
    )
    manager = _manager_with(reranker)
    manager.config = SimpleNamespace(
        max_results=10,
        min_score=0.4,
        sync_on_search=False,
        vector_weight=0.7,
        keyword_weight=0.3,
    )
    manager.embedding_provider = None
    manager._dirty = False
    manager.storage = SimpleNamespace(search_keyword=lambda **_: keyword_hits)

    results = asyncio.run(manager.search("query"))

    # Rank-normalized keyword scores are 1.0 / 0.75 / 0.5 / 0.25, so "d" is cut
    # by min_score=0.4 and never reaches the reranker despite its high score.
    assert reranker.calls == [["snippet a", "snippet b", "snippet c"]]
    assert [r.snippet for r in results] == ["snippet c", "snippet b", "snippet a"]


def test_sigmoid_maps_to_unit_interval():
    assert _sigmoid(0.0) == 0.5
    assert 0.0 < _sigmoid(-5.0) < 0.5 < _sigmoid(5.0) < 1.0


@pytest.mark.parametrize("provider", [None, "", "  "])
def test_create_reranker_disabled_without_provider(provider):
    assert create_reranker(provider) is None


def test_create_reranker_unknown_provider_is_disabled():
    assert create_reranker("no-such-provider") is None


def test_local_reranker_is_shared_and_loads_lazily(fake_sentence_transformers):
    first = create_reranker("local")
    second = create_reranker(" LOCAL ", "")

    assert isinstance(first, SentenceTransformerReranker)
    assert first is second
    assert first.model_name == reranker_module.DEFAULT_RERANK_MODEL
    assert fake_sentence_transformers.loads == 0

    first.rerank("q", ["a", "bbb"])
    first.rerank("q", ["cc"])

    assert fake_sentence_transformers.loads == 1


def test_local_reranker_load_failure_is_not_retried(fake_sentence_transformers):
    fake_sentence_transformers.fail = True
    reranker = create_reranker("local", "some/model")

    with pytest.raises(OSError):
        reranker.rerank("q", ["a"])
    with pytest.raises(RuntimeError):
        reranker.rerank("q", ["a"])

    assert fake_sentence_transformers.loads == 1


def test_registered_provider_receives_model():
    received = []

    def factory(model):
        received.append(model)
        return ScriptedReranker({})

    register_reranker_provider("scripted", factory)
    try:
        assert isinstance(create_reranker("scripted", "m1"), ScriptedReranker)
        assert received == ["m1"]
    finally:
        reranker_module._PROVIDERS.pop("scripted", None)


def test_unconfigured_rerank_never_imports_heavy_dependencies():
    # A fresh interpreter, so modules imported by other tests don't mask a
    # stray top-level import.
    script = textwrap.dedent(
        """
        import sys
        import agent.memory
        from agent.memory.reranker import create_default_reranker

        assert create_default_reranker() is None
        leaked = [m for m in ("sentence_transformers", "torch", "transformers") if m in sys.modules]
        assert not leaked, leaked
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, check=True)
