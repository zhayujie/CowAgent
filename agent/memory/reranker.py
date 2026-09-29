"""
Pluggable reranker for memory retrieval.

A reranker scores each candidate's text against the query directly, which is
usually more accurate than the fused cosine / BM25 score, and is used to
reorder the hybrid-search candidates. It is off by default and selected by
``rerank_provider`` in config.json.

Providers are registered by name, so a local model and a remote rerank API are
interchangeable behind the same ``Reranker`` interface. This module imports
nothing beyond the standard library: a provider's own dependencies (and any
model download) are only touched once a configured reranker scores its first
query.
"""

import math
import threading
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple

from common.log import logger

# bge-reranker-base has a 512-token input limit, which matches the 500-char
# ``snippet`` already carried by SearchResult.
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"


class Reranker(ABC):
    """Scores candidate documents against a query."""

    @abstractmethod
    def rerank(self, query: str, documents: List[str]) -> List[float]:
        """Score each document's relevance to the query.

        Returned scores are aligned 1:1 with ``documents``; higher is better.
        Raise on failure: the caller keeps the un-reranked order.
        """


class SentenceTransformerReranker(Reranker):
    """Local cross-encoder backed by ``sentence_transformers.CrossEncoder``.

    Construction is cheap: the dependency is imported and the model loaded
    (downloaded on first use) when the first query is scored. A failed load is
    remembered so later searches fail fast instead of retrying the download.
    """

    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL):
        self.model_name = model_name
        self._model = None
        self._load_error: Optional[Exception] = None
        # CrossEncoder.predict is not documented as thread-safe, and sessions
        # share one instance, so loading and scoring are serialized.
        self._lock = threading.Lock()

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        if not documents:
            return []
        with self._lock:
            model = self._load()
            logits = model.predict([(query, doc) for doc in documents])
        return [_sigmoid(float(score)) for score in logits]

    def _load(self):
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise RuntimeError(
                f"rerank model '{self.model_name}' is unavailable"
            ) from self._load_error
        try:
            from sentence_transformers import CrossEncoder

            logger.info(f"[Reranker] Loading local rerank model '{self.model_name}'")
            self._model = CrossEncoder(self.model_name)
        except ImportError as e:
            self._load_error = e
            logger.warning(
                "[Reranker] sentence-transformers is not installed; rerank is "
                "skipped. Install it with: pip install sentence-transformers"
            )
            raise
        except Exception as e:
            self._load_error = e
            logger.error(f"[Reranker] Failed to load rerank model '{self.model_name}': {e}")
            raise
        return self._model


def _sigmoid(value: float) -> float:
    """Squash a cross-encoder logit into [0, 1], overflow-safe."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


# Provider name -> factory taking the configured model name ("" = provider
# default). Factories must stay cheap: no heavy imports, no network, no model
# loading. A remote provider reads its own endpoint / key settings from config.
_PROVIDERS: Dict[str, Callable[[str], Reranker]] = {
    "local": lambda model: SentenceTransformerReranker(model or DEFAULT_RERANK_MODEL),
}

# One instance per (provider, model) for the whole process: every session's
# MemoryManager shares it, so a local model is loaded at most once.
_instances: Dict[Tuple[str, str], Reranker] = {}
_instances_lock = threading.Lock()


def register_reranker_provider(name: str, factory: Callable[[str], Reranker]) -> None:
    """Register (or replace) a reranker provider under ``name``."""
    key = name.strip().lower()
    with _instances_lock:
        _PROVIDERS[key] = factory
        for cached in [k for k in _instances if k[0] == key]:
            del _instances[cached]


def create_reranker(provider: Optional[str], model: Optional[str] = None) -> Optional[Reranker]:
    """Return the shared reranker for ``provider``, or None when disabled.

    An empty provider means rerank is off. An unknown provider is logged and
    treated as off, so a typo never breaks memory search.
    """
    name = (provider or "").strip().lower()
    if not name:
        return None
    factory = _PROVIDERS.get(name)
    if factory is None:
        logger.warning(
            f"[Reranker] Unknown rerank_provider '{name}', rerank is disabled. "
            f"Available: {', '.join(sorted(_PROVIDERS))}"
        )
        return None
    key = (name, (model or "").strip())
    with _instances_lock:
        reranker = _instances.get(key)
        if reranker is None:
            reranker = factory(key[1])
            _instances[key] = reranker
    return reranker


def create_default_reranker() -> Optional[Reranker]:
    """Build the reranker selected by ``rerank_provider`` / ``rerank_model``."""
    from config import conf

    return create_reranker(conf().get("rerank_provider", ""), conf().get("rerank_model", ""))


def clear_reranker_cache() -> None:
    """Drop the shared instances (for tests and config reloads)."""
    with _instances_lock:
        _instances.clear()
