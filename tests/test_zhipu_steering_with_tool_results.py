"""A steer that lands while tools run shares the user message with the
tool_result blocks (AgentStreamExecutor._append_steering). The GLM converter
must keep that text instead of forwarding only the tool results."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "zai" not in sys.modules:
    fake_zai = types.ModuleType("zai")
    fake_zai.ZhipuAiClient = object
    sys.modules["zai"] = fake_zai


def _steered_tool_result_message():
    from agent.protocol.agent_stream import AgentStreamExecutor

    executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
    executor._emit_event = lambda *a, **kw: None
    blocks = [{"type": "tool_result", "tool_use_id": "call_1", "content": "file listing"}]
    executor._append_steering(
        ["Stop and summarise what you found so far"],
        pending_tool_calls=[{"id": "call_2", "name": "bash", "arguments": {}}],
        content_blocks=blocks,
    )
    return {"role": "user", "content": blocks}


def test_steering_text_next_to_tool_results_reaches_glm():
    from models.zhipuai.zhipuai_bot import ZHIPUAIBot

    bot = ZHIPUAIBot.__new__(ZHIPUAIBot)
    history = [
        {"role": "user", "content": "look around"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "call_1", "name": "ls", "input": {}},
            {"type": "tool_use", "id": "call_2", "name": "bash", "input": {}},
        ]},
        _steered_tool_result_message(),
    ]

    converted = bot._convert_messages_to_zhipu_format(history)

    assert [m["role"] for m in converted] == ["user", "assistant", "tool", "tool", "user"]
    assert [m["tool_call_id"] for m in converted[2:4]] == ["call_1", "call_2"]
    assert "Stop and summarise what you found so far" in converted[-1]["content"]
