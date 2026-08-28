# encoding:utf-8
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_claude_tool_call_maps_reasoning_effort_to_output_config(monkeypatch):
    from config import conf
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    captured = {}
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)

    monkeypatch.setitem(conf(), "model", "claude-opus-5")
    monkeypatch.setitem(conf(), "character_desc", "")
    monkeypatch.setattr(bot, "_handle_sync_response", lambda request_params: captured.setdefault("request", request_params) or {"content": "ok"})

    bot.call_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        reasoning_effort="xhigh",
    )

    assert captured["request"]["output_config"] == {"effort": "xhigh"}


def test_claude_tool_call_preserves_existing_output_config(monkeypatch):
    from config import conf
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    captured = {}
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)

    monkeypatch.setitem(conf(), "model", "claude-sonnet-4-6")
    monkeypatch.setitem(conf(), "character_desc", "")
    monkeypatch.setattr(bot, "_handle_sync_response", lambda request_params: captured.setdefault("request", request_params) or {"content": "ok"})

    bot.call_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        output_config={"service_tier": "auto"},
        reasoning_effort="max",
    )

    assert captured["request"]["output_config"] == {
        "service_tier": "auto",
        "effort": "max",
    }
