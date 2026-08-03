# encoding:utf-8
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.setdefault("regex", re)


class _Response:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {
                    "reasoning_content": "thought",
                    "content": "answer",
                },
                "finish_reason": "stop",
            }]
        }


def test_kimi_k3_call_with_tools_sends_reasoning_effort(monkeypatch):
    from models.moonshot.moonshot_bot import MoonshotBot

    captured = {}
    bot = MoonshotBot.__new__(MoonshotBot)
    bot.args = {"model": "kimi-k3"}

    monkeypatch.setattr(bot, "_handle_sync_response", lambda request_body: captured.setdefault("request", request_body) or iter([]))

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        thinking={"type": "enabled"},
        reasoning_effort="high",
    )

    assert captured["request"]["model"] == "kimi-k3"
    assert "thinking" not in captured["request"]
    assert captured["request"]["reasoning_effort"] == "high"


def test_kimi_k3_call_with_tools_omits_thinking_when_requested_disabled(monkeypatch):
    from models.moonshot.moonshot_bot import MoonshotBot

    captured = {}
    bot = MoonshotBot.__new__(MoonshotBot)
    bot.args = {"model": "kimi-k3"}

    monkeypatch.setattr(bot, "_handle_sync_response", lambda request_body: captured.setdefault("request", request_body) or iter([]))

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        thinking={"type": "disabled"},
        reasoning_effort="max",
    )

    assert "thinking" not in captured["request"]
    assert captured["request"]["reasoning_effort"] == "max"


def test_kimi_k2_call_with_tools_does_not_send_reasoning_effort(monkeypatch):
    from models.moonshot.moonshot_bot import MoonshotBot

    captured = {}
    bot = MoonshotBot.__new__(MoonshotBot)
    bot.args = {"model": "kimi-k2.7-code"}

    monkeypatch.setattr(bot, "_handle_sync_response", lambda request_body: captured.setdefault("request", request_body) or iter([]))

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        thinking={"type": "enabled"},
        reasoning_effort="max",
    )

    assert "thinking" not in captured["request"]
    assert "reasoning_effort" not in captured["request"]


def test_kimi_sync_response_preserves_reasoning_content(monkeypatch):
    from models.moonshot import moonshot_bot
    from models.moonshot.moonshot_bot import MoonshotBot

    bot = MoonshotBot.__new__(MoonshotBot)

    monkeypatch.setattr(bot, "_build_headers", lambda: {})
    monkeypatch.setattr(moonshot_bot.requests, "post", lambda *args, **kwargs: _Response())

    result = list(bot._handle_sync_response({"model": "kimi-k3", "messages": []}))[0]

    assert result["content"][0] == {"type": "thinking", "thinking": "thought"}
    assert result["content"][1] == {"type": "text", "text": "answer"}
    assert result["stop_reason"] == "end_turn"
