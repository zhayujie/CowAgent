# encoding:utf-8
"""Claude's two mutually exclusive thinking controls.

Verified against the live API: 4.6-generation models and newer only accept
``adaptive`` (``enabled`` is a 400), 4.5 and earlier only accept ``enabled``
with a budget below ``max_tokens`` (``adaptive`` is a 400), and ``display``
must be set explicitly or the thinking blocks come back empty.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _bot_with_capture(monkeypatch, model):
    from config import conf
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    captured = {}
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    monkeypatch.setitem(conf(), "model", model)
    monkeypatch.setitem(conf(), "character_desc", "")
    monkeypatch.setattr(
        bot,
        "_handle_sync_response",
        lambda request_params: captured.setdefault("request", request_params) or {"content": "ok"},
    )
    return bot, captured


def _call(bot, **kwargs):
    bot.call_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        **kwargs,
    )


def test_adaptive_model_gets_adaptive_thinking_with_display(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "claude-sonnet-5")

    _call(bot, thinking={"type": "enabled"}, reasoning_effort="high")

    assert captured["request"]["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert captured["request"]["output_config"] == {"effort": "high"}


def test_legacy_model_gets_budget_below_max_tokens(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "claude-sonnet-4-5")

    _call(bot, thinking={"type": "enabled"}, max_tokens=8192)

    thinking = captured["request"]["thinking"]
    assert thinking["type"] == "enabled"
    assert 1024 <= thinking["budget_tokens"] < 8192


def test_legacy_budget_is_capped(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "claude-opus-4-5")

    _call(bot, thinking={"type": "enabled"}, max_tokens=200000)

    assert captured["request"]["thinking"]["budget_tokens"] == 16000


def test_thinking_disabled_is_sent_through(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "claude-sonnet-5")

    _call(bot, thinking={"type": "disabled"})

    assert captured["request"]["thinking"] == {"type": "disabled"}


def test_legacy_model_omits_thinking_when_budget_cannot_fit(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "claude-sonnet-4-5")

    _call(bot, thinking={"type": "enabled"}, max_tokens=512)

    assert "thinking" not in captured["request"]


def test_no_thinking_field_when_caller_passes_nothing(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "claude-sonnet-5")

    _call(bot, reasoning_effort="low")

    assert "thinking" not in captured["request"]


def test_pre_thinking_models_never_receive_the_field(monkeypatch):
    # Extended thinking only exists from 3.7 on; older models reject the field.
    for model in ("claude-3-5-sonnet-latest", "claude-3-opus", "some-proxy-model"):
        bot, captured = _bot_with_capture(monkeypatch, model)

        _call(bot, thinking={"type": "enabled"})
        assert "thinking" not in captured["request"], model

        bot, captured = _bot_with_capture(monkeypatch, model)
        _call(bot, thinking={"type": "disabled"})
        assert "thinking" not in captured["request"], model


def test_dated_model_names_route_by_prefix(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "claude-sonnet-5-20260101")
    _call(bot, thinking={"type": "enabled"})
    assert captured["request"]["thinking"]["type"] == "adaptive"

    bot, captured = _bot_with_capture(monkeypatch, "claude-opus-4-5-20251101")
    _call(bot, thinking={"type": "enabled"}, max_tokens=8192)
    assert captured["request"]["thinking"]["type"] == "enabled"


def test_sync_response_surfaces_thinking_as_reasoning_content(monkeypatch):
    import json

    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)
    monkeypatch.setattr(type(bot), "api_key", property(lambda self: "k"))
    monkeypatch.setattr(type(bot), "api_base", property(lambda self: "https://example.invalid/v1"))
    monkeypatch.setattr(type(bot), "proxy", property(lambda self: None))

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "id": "msg_1",
                "model": "claude-sonnet-5",
                "content": [
                    {"type": "thinking", "thinking": "let me count", "signature": "sig"},
                    {"type": "text", "text": "42"},
                ],
                "usage": {"input_tokens": 5, "output_tokens": 7},
            }

    monkeypatch.setattr("requests.post", lambda *a, **kw: _Resp())

    result = bot._handle_sync_response({"model": "claude-sonnet-5"})
    message = result["choices"][0]["message"]

    assert message["reasoning_content"] == "let me count"
    assert message["content"] == "42"
    assert json.dumps(result)  # response stays JSON-serializable
