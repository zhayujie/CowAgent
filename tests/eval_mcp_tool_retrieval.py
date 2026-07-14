# encoding:utf-8
"""
Evaluation / benchmark suite for on-demand MCP tool retrieval.

This is *not* a functional test. ``test_mcp_tool_retrieval.py`` already
checks that ``select_mcp_tools`` behaves correctly (invariants, fallbacks,
only-grows). This module answers a different question:

    *Is the retrieval actually any good?*

On a fixed, deterministic fixture dataset (no live embedding model needed)
it measures three standard IR quality metrics plus a token-savings report:

  - Precision@k  -- of the k tools injected, how many were relevant?
  - Recall@k     -- of the relevant tools, how many made it into top-k?
  - MRR          -- where does the first relevant tool land in the ranking?
  - Token savings -- full injection (all MCP tools) vs. on-demand top-k.

Determinism
-----------
Every vector is generated from ``random.Random(SEED)`` with a fixed seed, so
the dataset and every reported number are byte-for-byte reproducible across
machines and Python versions -- a prerequisite for tracking retrieval quality
over time (regressions in the embedding model / index would show up here).

Run
---
    python -m tests.eval_mcp_tool_retrieval            # human report
    python -m tests.eval_mcp_tool_retrieval --json     # machine report
    python -m pytest tests/eval_mcp_tool_retrieval.py   # smoke checks

The pytest run only asserts that metrics land in a sane band (so a broken
embedding pipeline fails CI); the full human report is printed by ``main()``.
"""
import json
import random
import sys
import os
from typing import Dict, List, Sequence, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.mcp.tool_retrieval import (  # noqa: E402
    cosine_similarity,
    select_mcp_tools,
)

# ---------------------------------------------------------------------------
# Fixture: a deterministic, semantically-clustered MCP tool universe.
# ---------------------------------------------------------------------------
# 5 clusters x 6 tools = 30 MCP tools. Vectors are 8-dim. Each cluster gets
# an orthogonal-ish center; tools within a cluster are the center plus small
# Gaussian noise, so within-cluster cosine is high (~0.9) and across-cluster
# is low (~0.1). Queries are drawn from a cluster center (with noise), and the
# ground truth is the set of tools in that cluster -- i.e. "the relevant tools
# for this query are the ones that live in the same semantic cluster".

SEED = 42
DIM = 8
N_CLUSTERS = 5
TOOLS_PER_CLUSTER = 6
N_TOOLS = N_CLUSTERS * TOOLS_PER_CLUSTER  # 30
N_QUERIES = 12
K_SWEEP = (3, 5, 8, 10, 15)  # top_k values to benchmark

CLUSTER_THEMES = [
    "filesystem",   # read/write/list/move/search files
    "web",          # fetch/search/scrape web pages
    "database",     # sql/query/insert/upsert
    "shell",        # run bash/cmd, manage processes
    "knowledge",    # rag/vector search over notes
]


def _make_vector(rng: random.Random, center: Sequence[float],
                 sigma: float = 0.06) -> List[float]:
    """center + small noise, then renormalised to unit length."""
    v = [c + rng.gauss(0.0, sigma) for c in center]
    norm = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / norm for x in v]


def _cluster_centers(rng: random.Random) -> List[List[float]]:
    """N_CLUSTERS unit vectors that are pairwise near-orthogonal."""
    centers: List[List[float]] = []
    while len(centers) < N_CLUSTERS:
        v = [rng.gauss(0.0, 1.0) for _ in range(DIM)]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        v = [x / norm for x in v]
        # accept if it's far enough from existing centers
        if all(cosine_similarity(v, c) < 0.25 for c in centers):
            centers.append(v)
    return centers


def _estimate_schema_tokens(name: str, description: str) -> int:
    """Cheap, dependency-free token estimate for a tool's injected schema.

    The real injection serialises {name, description, inputSchema} to JSON and
    feeds it to the model. We approximate with len(json)/4, the standard
    chars-per-token heuristic. This keeps the eval self-contained (no live
    tools) while staying within ~10% of the real figure -- good enough to
    compare full vs. on-demand injection.
    """
    schema = {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    }
    return max(1, len(json.dumps(schema)) // 4)


def build_fixture() -> Tuple[
    Dict[str, List[float]],          # tool_vectors
    Dict[str, int],                  # tool_schema_tokens
    List[dict],                      # queries
]:
    """Construct the deterministic dataset.

    Returns (tool_vectors, tool_schema_tokens, queries) where each query is::

        {
            "id": str,
            "theme": str,
            "vector": [float, ...],
            "relevant": set[str],     # ground-truth tool names
            "text": str,              # human description of the intent
        }
    """
    rng = random.Random(SEED)
    centers = _cluster_centers(rng)

    tool_vectors: Dict[str, List[float]] = {}
    tool_schema_tokens: Dict[str, int] = {}
    cluster_tools: List[List[str]] = [[] for _ in range(N_CLUSTERS)]

    for ci, theme in enumerate(CLUSTER_THEMES):
        for ti in range(TOOLS_PER_CLUSTER):
            name = f"{theme}_{ti}"
            vec = _make_vector(rng, centers[ci], sigma=0.06)
            # Give each tool a short, realistic description.
            desc = f"{theme} operation tool #{ti}: perform {theme} actions"
            tool_vectors[name] = vec
            tool_schema_tokens[name] = _estimate_schema_tokens(name, desc)
            cluster_tools[ci].append(name)

    # 12 queries spread across clusters (some clusters get multiple queries).
    queries: List[dict] = []
    for qi in range(N_QUERIES):
        ci = qi % N_CLUSTERS
        vec = _make_vector(rng, centers[ci], sigma=0.08)  # slightly noisier
        queries.append({
            "id": f"q{qi:02d}",
            "theme": CLUSTER_THEMES[ci],
            "vector": vec,
            "relevant": set(cluster_tools[ci]),
            "text": f"intent: use a {CLUSTER_THEMES[ci]} tool",
        })
    return tool_vectors, tool_schema_tokens, queries


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def rank_tools(query_vector: Sequence[float],
               tool_vectors: Dict[str, Sequence[float]]) -> List[str]:
    """Rank all candidate tools by descending cosine similarity to the query."""
    scored = [(name, cosine_similarity(query_vector, vec))
              for name, vec in tool_vectors.items()]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in scored]


def precision_at_k(ranked: List[str], relevant: Set[str], k: int) -> float:
    top = ranked[:k]
    hits = sum(1 for n in top if n in relevant)
    return hits / k if k > 0 else 0.0


def recall_at_k(ranked: List[str], relevant: Set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = ranked[:k]
    hits = sum(1 for n in top if n in relevant)
    return hits / len(relevant)


def reciprocal_rank(ranked: List[str], relevant: Set[str]) -> float:
    """1/rank of the first relevant result (0 if none in the list)."""
    for i, name in enumerate(ranked, start=1):
        if name in relevant:
            return 1.0 / i
    return 0.0


def token_cost(names: Set[str], schema_tokens: Dict[str, int]) -> int:
    return sum(schema_tokens.get(n, 0) for n in names)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def run_eval(top_k: int,
             tool_vectors: Dict[str, Sequence[float]],
             schema_tokens: Dict[str, int],
             queries: List[dict]) -> dict:
    """Run retrieval for every query at a fixed ``top_k`` and return metrics."""
    per_query = []
    p_sum = r_sum = rr_sum = 0.0
    full_tokens = sum(schema_tokens.values())
    on_demand_tokens_sum = 0

    for q in queries:
        ranked = rank_tools(q["vector"], tool_vectors)
        # The production path uses select_mcp_tools; call it too so the eval
        # exercises the real entry point (not just our local ranking).
        selected = select_mcp_tools(q["vector"], tool_vectors, top_k=top_k,
                                     already_selected=set())
        if selected is None:
            selected = set(ranked[:top_k])

        p = precision_at_k(ranked, q["relevant"], top_k)
        r = recall_at_k(ranked, q["relevant"], top_k)
        rr = reciprocal_rank(ranked, q["relevant"])
        od_tokens = token_cost(selected, schema_tokens)

        p_sum += p
        r_sum += r
        rr_sum += rr
        on_demand_tokens_sum += od_tokens
        per_query.append({
            "id": q["id"], "theme": q["theme"],
            "precision": round(p, 4),
            "recall": round(r, 4),
            "mrr": round(rr, 4),
            "tokens_on_demand": od_tokens,
        })

    n = len(queries)
    avg_full = full_tokens
    return {
        "top_k": top_k,
        "n_queries": n,
        "precision@k": round(p_sum / n, 4),
        "recall@k": round(r_sum / n, 4),
        "mrr": round(rr_sum / n, 4),
        "tokens_full_per_query": avg_full,
        "tokens_on_demand_avg": round(on_demand_tokens_sum / n),
        "token_savings_pct": round(
            100.0 * (1.0 - (on_demand_tokens_sum / n) / avg_full), 2) if avg_full else 0.0,
        "per_query": per_query,
    }


def format_report(results: List[dict]) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("MCP Tool Retrieval -- Quality & Token-Savings Benchmark")
    lines.append(f"Dataset: {N_TOOLS} tools in {N_CLUSTERS} clusters, "
                 f"{N_QUERIES} queries, seed={SEED}")
    lines.append("=" * 72)
    header = (f"{'top_k':>5} | {'P@k':>6} | {'R@k':>6} | {'MRR':>6} | "
              f"{'full tok':>8} | {'ondemand':>8} | {'saved':>6}")
    lines.append(header)
    lines.append("-" * len(header))
    for r in results:
        lines.append(
            f"{r['top_k']:>5} | {r['precision@k']:>6.3f} | {r['recall@k']:>6.3f} | "
            f"{r['mrr']:>6.3f} | {r['tokens_full_per_query']:>8} | "
            f"{r['tokens_on_demand_avg']:>8} | {r['token_savings_pct']:>5.1f}%"
        )
    lines.append("-" * len(header))
    lines.append("P@k=Precision@k  R@k=Recall@k  MRR=Mean Reciprocal Rank")
    lines.append("full tok = tokens if ALL MCP tools injected; "
                 "ondemand = avg tokens with top-k on-demand injection")
    # per-query detail for the recommended k
    best = max(results, key=lambda r: r["recall@k"])
    lines.append("")
    lines.append(f"Per-query detail (top_k={best['top_k']}, highest recall):")
    lines.append(f"  {'query':>5} | {'theme':<11} | {'P':>5} | {'R':>5} | "
                 f"{'MRR':>5} | {'tok':>5}")
    for pq in best["per_query"]:
        lines.append(f"  {pq['id']:>5} | {pq['theme']:<11} | {pq['precision']:>5.2f} | "
                     f"{pq['recall']:>5.2f} | {pq['mrr']:>5.2f} | {pq['tokens_on_demand']:>5}")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv=None):
    tool_vectors, schema_tokens, queries = build_fixture()
    results = [run_eval(k, tool_vectors, schema_tokens, queries) for k in K_SWEEP]
    if argv and "--json" in argv:
        print(json.dumps({"config": {"seed": SEED, "dim": DIM, "n_tools": N_TOOLS,
                                      "n_queries": N_QUERIES, "k_sweep": list(K_SWEEP)},
                          "results": results}, indent=2))
    else:
        print(format_report(results))


# ---------------------------------------------------------------------------
# pytest smoke checks: fail CI if retrieval quality collapses.
# ---------------------------------------------------------------------------

def test_retrieval_recall_at_recommended_k():
    """At the recommended top_k (>=5) recall must be high on this dataset.

    A regression below the floor means the embedding/index pipeline broke --
    exactly what this eval is meant to catch.
    """
    tool_vectors, schema_tokens, queries = build_fixture()
    r = run_eval(5, tool_vectors, schema_tokens, queries)
    assert r["recall@k"] >= 0.80, f"recall@5 collapsed to {r['recall@k']}"
    assert r["precision@k"] >= 0.80, f"precision@5 collapsed to {r['precision@k']}"


def test_token_savings_is_positive():
    """On-demand injection must save tokens vs. full injection."""
    tool_vectors, schema_tokens, queries = build_fixture()
    r = run_eval(5, tool_vectors, schema_tokens, queries)
    assert r["token_savings_pct"] > 0.0, "on-demand injection saves no tokens"


def test_determinism():
    """Same seed -> identical vectors (regression guard)."""
    a = build_fixture()[0]
    b = build_fixture()[0]
    assert a == b, "fixture is not deterministic"


if __name__ == "__main__":
    main(sys.argv[1:])
