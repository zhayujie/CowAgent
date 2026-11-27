"""Responses usage keeps the cached prompt tokens the console reports."""
from agent.protocol.agent_stream import AgentStreamExecutor
from models.openai.responses_adapter import (
    responses_stream_to_chat_chunks,
    responses_to_chat_completion,
)

USAGE = {
    "input_tokens": 1200,
    "input_tokens_details": {"cached_tokens": 1024},
    "output_tokens": 40,
    "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 1240,
}


def _response(usage):
    return {
        "id": "resp_1",
        "model": "gpt-test",
        "status": "completed",
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "hi"}],
        }],
        "usage": usage,
    }


def _cache_hit(usage):
    return AgentStreamExecutor._normalize_stream_usage(usage)["prompt_cache_hit_tokens"]


def test_sync_response_reports_cached_prompt_tokens():
    usage = responses_to_chat_completion(_response(USAGE))["usage"]

    assert usage["prompt_tokens"] == 1200
    assert _cache_hit(usage) == 1024


def test_stream_response_reports_cached_prompt_tokens():
    chunks = list(responses_stream_to_chat_chunks(iter([
        {"type": "response.output_text.delta", "delta": "hi"},
        {"type": "response.completed", "response": _response(USAGE)},
    ]), model="gpt-test"))
    usage = chunks[-1]["usage"]

    assert usage["prompt_tokens"] == 1200
    assert _cache_hit(usage) == 1024


def test_usage_without_cached_tokens_is_unchanged():
    usage = responses_to_chat_completion(_response({
        "input_tokens": 12, "output_tokens": 3, "total_tokens": 15,
    }))["usage"]

    assert usage == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
