"""An empty summary answer is a failed summary, not "nothing worth keeping".

The trim/overflow flush asked for at most 500 output tokens. A thinking
model spends that budget on reasoning (the Claude bot notes thinking tokens
count towards the same limit) and comes back with no text. The flush read
the empty answer as the "None"/"无" sentinel, marked the discarded turns as
flushed for good and injected no context summary, so those turns were lost
from both the live context and long-term memory.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory.summarizer import MemoryFlushManager

SUMMARY = "- the user picked copy-on-write for the cache layer\n"
REASONING_TOKENS = 800


def _text(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


_PLAIN_WINDOW = [
    _text("user", "should the cache layer use copy-on-write snapshots?"),
    _text("assistant", "Yes, copy-on-write keeps readers lock-free during a swap."),
]

# Starts on an assistant turn, so the rule-based fallback has nothing to record.
_LOST_WINDOW = [
    _text(
        "assistant",
        "Here is the plan we agreed on: copy-on-write snapshots for the cache "
        "layer, swapped atomically by the refresher thread.",
    ),
]


class _ReasoningModel:
    """Reasoning counts against max_tokens; a spent budget leaves no text."""

    def __init__(self):
        self.max_tokens = []

    def call(self, request):
        self.max_tokens.append(request.max_tokens)
        if request.max_tokens is not None and request.max_tokens <= REASONING_TOKENS:
            return {"choices": [{"message": {"content": None}, "finish_reason": "length"}]}
        return {"choices": [{"message": {"content": SUMMARY}, "finish_reason": "stop"}]}


class _FixedModel:
    def __init__(self, content):
        self.content = content
        self.calls = 0

    def call(self, request):
        self.calls += 1
        return {"choices": [{"message": {"content": self.content}}]}


def _flush(manager, window):
    injected = []
    dispatched = manager.flush_from_messages(
        window, context_summary_callback=injected.append
    )
    if dispatched:
        thread = manager._last_flush_thread
        thread.join(timeout=30)
        assert not thread.is_alive(), "the flush worker did not finish"
    return dispatched, injected


def _memory(workspace):
    return "".join(p.read_text(encoding="utf-8") for p in sorted(workspace.glob("memory/*.md")))


def test_a_thinking_model_gets_room_to_answer_after_reasoning(tmp_path):
    model = _ReasoningModel()
    manager = MemoryFlushManager(tmp_path, model)

    _, injected = _flush(manager, _PLAIN_WINDOW)

    assert "copy-on-write for the cache layer" in _memory(tmp_path)
    assert injected and "copy-on-write for the cache layer" in injected[0]


@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_an_empty_answer_falls_back_instead_of_dropping_the_turns(tmp_path, content):
    manager = MemoryFlushManager(tmp_path, _FixedModel(content))

    _, injected = _flush(manager, _PLAIN_WINDOW)

    # Same as an unreachable provider: the rule-based digest is kept.
    assert "copy-on-write" in _memory(tmp_path)
    assert injected


def test_an_empty_answer_with_nothing_to_fall_back_on_stays_retryable(tmp_path):
    model = _FixedModel(None)
    manager = MemoryFlushManager(tmp_path, model)

    assert _flush(manager, _LOST_WINDOW)[0] is True
    assert _memory(tmp_path) == ""

    model.content = SUMMARY
    dispatched, injected = _flush(manager, _LOST_WINDOW)

    assert dispatched is True, "the turns were marked flushed after an empty answer"
    assert model.calls == 2
    assert "copy-on-write for the cache layer" in _memory(tmp_path)
    assert injected


@pytest.mark.parametrize("sentinel", ["None", "无", " none \n"])
def test_the_explicit_sentinel_still_means_nothing_to_keep(tmp_path, sentinel):
    model = _FixedModel(sentinel)
    manager = MemoryFlushManager(tmp_path, model)

    _, injected = _flush(manager, _PLAIN_WINDOW)

    assert _memory(tmp_path) == ""
    assert injected == []
    # Settled as done: the same turns are not summarised again.
    assert manager.flush_from_messages(_PLAIN_WINDOW) is False
    assert model.calls == 1
