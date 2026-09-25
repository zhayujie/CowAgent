"""
Cross-encoder reranker for memory retrieval.

A cross-encoder judges the query against each candidate's text directly and is
far more accurate than the fused cosine / BM25 score, so it is used to
precision-reorder the merged hybrid-search candidates. It is optional and off
by default: loading a cross-encoder pulls in ``sentence-transformers`` (and
torch) plus a model download, so it is only constructed when ``rerank_enabled``
is set in config.
"""

import math
from abc import ABC, abstractmethod
from typing import List, Optional

# Default cross-encoder. bge-reranker-base has a 512-token input limit, which
# matches the 500-char ``snippet`` already carried by SearchResult.
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"


class Reranker(ABC):
    """Base class for cross-encoder rerankers."""

    @abstractmethod
    def rerank(self, query: str, documents: List[str]) -> List[float]:
        """Score each document's relevance to the query, in [0, 1].

        Returned scores are aligned 1:1 with ``documents``; higher is better.
        """
        pass


class SentenceTransformerReranker(Reranker):
    """Cross-encoder reranker backed by ``sentence_transformers.CrossEncoder``.

    The heavy dependency is imported inside ``__init__`` so the default memory
    path stays free of torch/sentence-transformers until a reranker is actually
    requested.
    """

    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL):
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        if not documents:
            return []
        pairs = [(query, doc) for doc in documents]
        logits = self._model.predict(pairs)
        return [_sigmoid(float(score)) for score in logits]


def _sigmoid(value: float) -> float:
    """Squash a cross-encoder logit into [0, 1], overflow-safe."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def create_reranker(model_name: Optional[str] = None) -> Optional[Reranker]:
    """Build a reranker, or None when the optional dependency is missing.

    Returns None (rather than raising) so callers degrade gracefully to
    un-reranked retrieval, mirroring how an absent embedding provider degrades
    to keyword-only search.
    """
    resolved = model_name or DEFAULT_RERANK_MODEL
    try:
        return SentenceTransformerReranker(resolved)
    except ImportError:
        from common.log import logger

        logger.warning(
            "[Reranker] sentence-transformers is not installed; rerank is "
            "disabled. Install it with: pip install sentence-transformers"
        )
        return None
    except Exception as e:
        from common.log import logger

        logger.error(f"[Reranker] Failed to load reranker '{resolved}': {e}")
        return None
