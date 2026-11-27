"""The trim budget must count the tool schemas, not just prompt + history.

agent.py's usage chart already admits the gap ("the trimmer budgets the
system prompt and history but not the tool schemas, which still occupy the
window"): on tool-heavy installs (MCP servers, many skills) the estimated
history fit the window while the real prompt — schema definitions included —
did not, so the run paid a 400-overflow round-trip before compaction could
react, and a persistent underestimate escalated to the hard context reset.
"""
from types import SimpleNamespace

from agent.protocol.agent_stream import AgentStreamExecutor
from tests.test_agent_trim_budget import _MemoryManager, _make_turn_messages


class _BigTool:
    name = "big"
    description = "x" * 4000
    params = {"type": "object", "properties": {}}

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def get_json_schema():
        return {}


def _executor(tools, tokens_per_message=10, max_tokens=130):
    memory_manager = _MemoryManager()
    agent = SimpleNamespace(
        memory_manager=memory_manager,
        max_context_tokens=max_tokens,
        _get_model_context_window=lambda: max_tokens,
        _get_output_reserve_tokens=lambda: 0,
        _estimate_message_tokens=lambda message: tokens_per_message,
        _estimate_text_tokens=lambda text: max(1, len(text) // 4),
    )
    executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
    executor.agent = agent
    executor.messages = _make_turn_messages(6)   # 12 messages x 10 tokens = 120
    executor.system_prompt = "system"            # _estimate_message_tokens -> 10
    executor.max_context_turns = 50
    executor.tools = tools
    return executor, memory_manager


def test_schema_tokens_are_counted_in_the_budget():
    # 120 history + 10 system = 130 fits the old budget exactly; the big
    # tool's schema (~1000 estimated tokens) pushes the real prompt over.
    executor, memory_manager = _executor({"big": _BigTool()})

    assert executor._tool_schema_tokens() > 500
    executor._trim_messages()

    # The trim had to act: older turns were flushed to memory instead of
    # silently keeping an over-window prompt.
    assert memory_manager.flush_calls, "the schema tokens were not budgeted"


def test_history_only_budgets_still_trim_on_their_own():
    # No tools: the original behaviour (120 + 10 <= 130 keeps everything).
    executor, memory_manager = _executor({})

    assert executor._tool_schema_tokens() == 0
    executor._trim_messages()

    assert memory_manager.flush_calls == []
    assert len(executor.messages) == 12


def test_the_overflow_budget_subtracts_the_schemas_too():
    executor, _ = _executor({"big": _BigTool()})
    schema_tokens = executor._tool_schema_tokens()

    budget = executor._overflow_input_budget(
        "maximum context length is 200000 tokens, and you requested 250000 "
        "tokens (200000 in the messages, 50000 in the completion)"
    )

    # window 200000 - completion 50000 - system 10 - schemas, 10% safety.
    expected = int((200000 - 50000 - 10 - schema_tokens) * 0.9)
    assert budget == expected
