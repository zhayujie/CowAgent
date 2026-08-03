# encoding:utf-8
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "dashscope" not in sys.modules:
    fake_dashscope = types.ModuleType("dashscope")
    fake_generation_models = types.SimpleNamespace(
        qwen_turbo="qwen-turbo",
        qwen_plus="qwen-plus",
        qwen_max="qwen-max",
        bailian_v1="qwen-bailian-v1",
    )
    fake_dashscope.Generation = types.SimpleNamespace(Models=fake_generation_models)
    fake_dashscope.MultiModalConversation = object
    sys.modules["dashscope"] = fake_dashscope


def _bot_with_capture(monkeypatch, model_name):
    from models.dashscope.dashscope_bot import DashscopeBot

    captured = {}
    bot = DashscopeBot.__new__(DashscopeBot)
    bot.model_name = model_name

    monkeypatch.setattr(bot, "_convert_messages_to_dashscope_format", lambda messages: messages)
    monkeypatch.setattr(bot, "_convert_tools_to_dashscope_format", lambda tools: tools)

    def fake_handle_sync_response(model_name, messages, parameters):
        captured["model_name"] = model_name
        captured["messages"] = messages
        captured["parameters"] = parameters
        return {"content": "ok"}

    monkeypatch.setattr(bot, "_handle_sync_response", fake_handle_sync_response)
    return bot, captured


def test_dashscope_qwen38_sends_reasoning_effort_in_parameters(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "qwen3.8-max-preview")

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        thinking={"type": "enabled"},
        reasoning_effort="medium",
        thinking_budget=4096,
    )

    assert captured["parameters"]["enable_thinking"] is True
    assert captured["parameters"]["reasoning_effort"] == "medium"
    assert captured["parameters"]["preserve_thinking"] is False
    assert "thinking_budget" not in captured["parameters"]


def test_dashscope_qwen38_forces_thinking_when_requested_disabled(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "qwen3.8-max-preview")

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        thinking={"type": "disabled"},
        reasoning_effort="xhigh",
    )

    assert captured["parameters"]["enable_thinking"] is True
    assert captured["parameters"]["preserve_thinking"] is False
    assert captured["parameters"]["reasoning_effort"] == "xhigh"


def test_dashscope_direct_glm_sends_enable_thinking_and_reasoning_effort(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "glm-5.2")

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        thinking={"type": "enabled"},
        reasoning_effort="max",
    )

    assert captured["parameters"]["enable_thinking"] is True
    assert captured["parameters"]["reasoning_effort"] == "max"


def test_dashscope_existing_qwen_thinking_budget_still_works(monkeypatch):
    bot, captured = _bot_with_capture(monkeypatch, "qwen3.7-plus")

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
        thinking={"type": "enabled"},
        thinking_budget=4096,
    )

    assert captured["parameters"]["enable_thinking"] is True
    assert captured["parameters"]["thinking_budget"] == 4096
    assert "reasoning_effort" not in captured["parameters"]
