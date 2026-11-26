# encoding:utf-8
"""embed_batch returns vectors in input order, using each response item's `index`."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.embedding.provider import OpenAIEmbeddingProvider


class ScriptedProvider(OpenAIEmbeddingProvider):
    def __init__(self, responses, max_batch_size=64, model="text-embedding-3-small", api_base=None):
        super().__init__(model=model, api_key="test-key", api_base=api_base, max_batch_size=max_batch_size)
        self.responses = list(responses)

    def _call_api(self, input_data):
        return self.responses.pop(0)


def _item(index, vector_id):
    return {"object": "embedding", "index": index, "embedding": [float(vector_id), 0.0, 1.0]}


def test_out_of_order_pages_are_reordered_by_index():
    # Each page has its own index space starting at 0.
    provider = ScriptedProvider([
        {"data": [_item(1, 1), _item(0, 0)]},
        {"data": [_item(1, 3), _item(0, 2)]},
    ], max_batch_size=2)
    vectors = provider.embed_batch([f"text {i}" for i in range(4)])
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0, 3.0]


def test_items_without_index_keep_response_order():
    data = [_item(0, 0), _item(0, 1)]
    for item in data:
        del item["index"]
    vectors = ScriptedProvider([{"data": data}]).embed_batch(["a", "b"])
    assert [v[0] for v in vectors] == [0.0, 1.0]


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


@pytest.mark.parametrize("model, api_base", [
    ("gemini-embedding-2", GEMINI_BASE),
    ("gemini-embedding-001", GEMINI_BASE),
    ("gemini-embedding-2", "https://example.com/v1"),
])
def test_gemini_batch_accepts_omitted_zero_index(model, api_base):
    provider = ScriptedProvider(
        [{"data": [{"embedding": [0.1, 0.2]}, {"index": 1, "embedding": [0.3, 0.4]}]}],
        model=model, api_base=api_base,
    )
    assert provider.embed_batch(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_batch_reorders_items_with_omitted_zero_index():
    data = [
        {"index": 2, "embedding": [2.0]},
        {"embedding": [0.0]},
        {"index": 1, "embedding": [1.0]},
    ]
    provider = ScriptedProvider([{"data": data}])
    assert provider.embed_batch(["a", "b", "c"]) == [[0.0], [1.0], [2.0]]


@pytest.mark.parametrize("item_indices", [
    [{"index": None}, {"index": 1}],
    [{}, {"index": True}],
    [{}, {"index": 2}],
    [{}, {"index": 0}],
    [{}, {"index": 1}, {"index": 1}],
    [{}, {"index": 1}, {}],
])
def test_invalid_partial_indexes_are_rejected(item_indices):
    data = [{"embedding": [float(i)], **fields} for i, fields in enumerate(item_indices)]
    provider = ScriptedProvider([{"data": data}])
    with pytest.raises(ValueError, match="indexes must cover every input"):
        provider.embed_batch(["text"] * len(data))
