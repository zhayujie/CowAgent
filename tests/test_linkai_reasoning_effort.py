# encoding:utf-8
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _call_and_capture(monkeypatch, model_name, **kwargs):
    from config import conf
    from models.linkai.link_ai_bot import LinkAIBot

    captured = {}
    bot = LinkAIBot.__new__(LinkAIBot)

    monkeypatch.setitem(conf(), "model", model_name)
    monkeypatch.setitem(conf(), "linkai_api_key", "test-key")
    monkeypatch.setattr(
        bot,
        "_handle_linkai_sync_response",
        lambda base_url, headers, body: captured.setdefault("body", body),
    )

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        model=model_name,
        **kwargs,
    )
    return captured["body"]


def test_linkai_deepseek_v4_forwards_reasoning_effort(monkeypatch):
    body = _call_and_capture(
        monkeypatch,
        "deepseek-v4-flash",
        thinking={"type": "enabled"},
        reasoning_effort="max",
    )

    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "max"


def test_linkai_glm_forwards_reasoning_effort(monkeypatch):
    body = _call_and_capture(
        monkeypatch,
        "glm-5.2",
        thinking={"type": "enabled"},
        reasoning_effort="medium",
    )

    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "medium"


def test_linkai_kimi_k3_forwards_effort_without_thinking(monkeypatch):
    body = _call_and_capture(
        monkeypatch,
        "kimi-k3",
        thinking={"type": "enabled"},
        reasoning_effort="low",
    )

    assert "thinking" not in body
    assert body["reasoning_effort"] == "low"


def test_linkai_unverified_model_omits_reasoning_effort(monkeypatch):
    body = _call_and_capture(
        monkeypatch,
        "gpt-5.4",
        thinking={"type": "enabled"},
        reasoning_effort="high",
    )

    assert body["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in body
