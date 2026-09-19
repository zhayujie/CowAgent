"""Regression tests for budget-aware context trimming (#3178).

``_trim_messages()`` used to drop the older half of turns (and fire a
summary LLM call) whenever turn count exceeded ``max_context_turns``,
even when the estimated token total was well under the model budget.

A single token-budget-first pass must:
- keep every complete turn that still fits the input window
- discard only the minimum older turns needed when over budget
- use ``max_context_turns`` as a safety net, not an independent half-drop
- flush / summarize only when turns were actually discarded
"""

from types import SimpleNamespace

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.message_utils import identify_complete_turns


class _MemoryManager:
    def __init__(self):
        self.flush_calls = []

    def flush_memory(self, **kwargs):
        self.flush_calls.append(kwargs)


def _make_turn_messages(turn_count):
    messages = []
    for i in range(turn_count):
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": f"q{i}"}],
        })
        messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": f"a{i}"}],
        })
    return messages


def _make_executor(
    *,
    turn_count,
    max_context_turns,
    tokens_per_message,
    max_tokens,
    messages=None,
):
    memory_manager = _MemoryManager()
    agent = SimpleNamespace(
        memory_manager=memory_manager,
        max_context_tokens=max_tokens,
        _get_model_context_window=lambda: max_tokens,
        _get_output_reserve_tokens=lambda: 0,
        _estimate_message_tokens=lambda message: tokens_per_message,
    )
    executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
    executor.agent = agent
    executor.messages = messages if messages is not None else _make_turn_messages(turn_count)
    executor.system_prompt = "system"
    executor.max_context_turns = max_context_turns
    return executor, memory_manager


def _user_texts(messages):
    return [
        block["text"]
        for msg in messages
        if msg.get("role") == "user"
        for block in (msg.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "text" and "text" in block
    ]


def test_many_short_turns_under_budget_do_not_summarize():
    """31 one-token turns fit a 1000-token budget: keep all, no summary."""
    executor, memory_manager = _make_executor(
        turn_count=31,
        max_context_turns=30,
        tokens_per_message=1,
        max_tokens=1000,
    )

    executor._trim_messages()

    assert memory_manager.flush_calls == []
    assert len(identify_complete_turns(executor.messages)) == 31
    assert executor.messages[-1]["content"][0]["text"] == "a30"


def test_over_budget_still_trims():
    """Turns that exceed the token budget must still be discarded."""
    executor, memory_manager = _make_executor(
        turn_count=10,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=200,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) < 10
    assert len(kept_turns) >= 1
    assert memory_manager.flush_calls, "over-budget trim should flush discarded turns"
    assert executor.messages[-1]["content"][0]["text"] == "a9"


def test_over_budget_discards_minimum_turns_not_half():
    """Budget that fits 7 of 10 equal turns must keep 7, not drop half.

    Each turn is 2 messages * 100 tokens = 200. System prompt is 100.
    max_tokens=1500 leaves a 1400-token turn budget = 7 turns.
    The old half-drop would keep 5.
    """
    executor, memory_manager = _make_executor(
        turn_count=10,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=1500,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) == 7
    assert _user_texts(executor.messages) == [f"q{i}" for i in range(3, 10)]
    assert executor.messages[-1]["content"][0]["text"] == "a9"
    assert len(memory_manager.flush_calls) == 1
    flushed = memory_manager.flush_calls[0]["messages"]
    assert _user_texts(flushed) == ["q0", "q1", "q2"]
    assert memory_manager.flush_calls[0]["reason"] == "trim"
    assert memory_manager.flush_calls[0]["context_summary_callback"] is not None


def test_over_budget_respects_max_context_turns_safety_net():
    """When already over budget, cap kept turns at max_context_turns.

    20 turns * 20 tokens = 400, system = 10, max_tokens=250 -> 240-token
    budget keeps 12 turns. Safety net then caps at 8. Half-drop would keep 10.
    """
    executor, memory_manager = _make_executor(
        turn_count=20,
        max_context_turns=8,
        tokens_per_message=10,
        max_tokens=250,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) == 8
    assert _user_texts(executor.messages) == [f"q{i}" for i in range(12, 20)]
    assert executor.messages[-1]["content"][0]["text"] == "a19"
    assert memory_manager.flush_calls


def test_single_turn_over_budget_is_kept_without_flush():
    """A single oversized turn is kept so the current exchange is not lost."""
    executor, memory_manager = _make_executor(
        turn_count=1,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=50,
    )

    executor._trim_messages()

    assert len(identify_complete_turns(executor.messages)) == 1
    assert executor.messages[-1]["content"][0]["text"] == "a0"
    assert memory_manager.flush_calls == []


def test_trim_keeps_tool_use_and_tool_result_together():
    """Discarded older turns must not split a kept tool_use/tool_result pair."""
    messages = _make_turn_messages(2)
    messages.extend([
        {"role": "user", "content": [{"type": "text", "text": "q2"}]},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "call_1",
                "name": "ls",
                "input": {"path": "."},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "file.txt",
            }],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "a2"}]},
    ])
    executor, memory_manager = _make_executor(
        turn_count=3,
        max_context_turns=30,
        tokens_per_message=100,
        max_tokens=500,
        messages=messages,
    )

    executor._trim_messages()

    kept_turns = identify_complete_turns(executor.messages)
    assert len(kept_turns) == 1
    block_types = [
        block.get("type")
        for msg in executor.messages
        for block in (msg.get("content") or [])
        if isinstance(block, dict)
    ]
    assert "tool_use" in block_types
    assert "tool_result" in block_types
    assert executor.messages[-1]["content"][0]["text"] == "a2"
    assert memory_manager.flush_calls
    assert _user_texts(memory_manager.flush_calls[0]["messages"]) == ["q0", "q1"]
