"""Regression tests for budget-aware context trimming."""

from types import SimpleNamespace

from agent.protocol.agent_stream import AgentStreamExecutor


class _MemoryManager:
    def __init__(self):
        self.flush_calls = []

    def flush_memory(self, **kwargs):
        self.flush_calls.append(kwargs)


def _make_executor(*, turn_count, max_context_turns, estimated_tokens, max_tokens):
    memory_manager = _MemoryManager()
    agent = SimpleNamespace(
        memory_manager=memory_manager,
        max_context_turns=max_context_turns,
        max_context_tokens=max_tokens,
        _get_model_context_window=lambda: max_tokens,
        _get_output_reserve_tokens=lambda: 0,
        _estimate_message_tokens=lambda message: 0,
    )
    executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
    executor.agent = agent
    executor.messages = [{"role": "user", "content": "existing"}]
    executor.system_prompt = "system"
    executor.max_context_turns = max_context_turns
    turns = [
        {"messages": [{"role": "user", "content": f"turn-{i}"}]}
        for i in range(turn_count)
    ]
    executor._truncate_historical_tool_results = lambda: None
    executor._identify_complete_turns = lambda: turns
    executor._estimate_turn_tokens = lambda turn: estimated_tokens
    return executor, memory_manager


def test_under_budget_does_not_summarize_when_turn_limit_is_exceeded():
    executor, memory_manager = _make_executor(
        turn_count=31,
        max_context_turns=30,
        estimated_tokens=1,
        max_tokens=1000,
    )

    executor._trim_messages()

    assert memory_manager.flush_calls == []
    assert len(executor.messages) == 31
