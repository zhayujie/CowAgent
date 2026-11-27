"""ZhipuAI usage keeps the cached prompt tokens the console reports."""
from types import SimpleNamespace as NS

from agent.protocol.agent_stream import AgentStreamExecutor
from models.zhipuai.zhipuai_bot import ZHIPUAIBot

# Shape of zai-sdk's CompletionUsage: cache hits are part of prompt_tokens.
USAGE = NS(
    prompt_tokens=1200,
    prompt_tokens_details=NS(cached_tokens=1024),
    completion_tokens=40,
    completion_tokens_details=None,
    total_tokens=1240,
)


def _bot(monkeypatch, result):
    bot = ZHIPUAIBot.__new__(ZHIPUAIBot)
    monkeypatch.setattr(bot, "_create_completion", lambda params: result)
    return bot


def _cache_hit(usage):
    return AgentStreamExecutor._normalize_stream_usage(usage)["prompt_cache_hit_tokens"]


def test_stream_usage_reports_cached_prompt_tokens(monkeypatch):
    stream = [
        NS(id="c1", created=0, model="glm-5.2", usage=None, choices=[NS(
            delta=NS(role="assistant", content="hi", reasoning_content=None, tool_calls=None),
            finish_reason=None,
        )]),
        NS(id="c1", created=0, model="glm-5.2", usage=USAGE, choices=[]),
    ]
    chunks = list(_bot(monkeypatch, iter(stream))._handle_stream_response({}))
    usage = chunks[-1]["usage"]

    assert usage["prompt_tokens"] == 1200
    assert _cache_hit(usage) == 1024


def test_sync_usage_reports_cached_prompt_tokens(monkeypatch):
    response = NS(id="c1", created=0, model="glm-5.2", usage=USAGE, choices=[NS(
        message=NS(role="assistant", content="hi", tool_calls=None),
        finish_reason="stop",
    )])
    usage = _bot(monkeypatch, response)._handle_sync_response({})["usage"]

    assert usage["prompt_tokens"] == 1200
    assert _cache_hit(usage) == 1024


def test_usage_without_cached_tokens_is_unchanged(monkeypatch):
    usage = NS(prompt_tokens=12, prompt_tokens_details=None, completion_tokens=3, total_tokens=15)
    response = NS(id="c1", created=0, model="glm-5.2", usage=usage, choices=[NS(
        message=NS(role="assistant", content="hi", tool_calls=None),
        finish_reason="stop",
    )])

    result = _bot(monkeypatch, response)._handle_sync_response({})

    assert result["usage"] == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
