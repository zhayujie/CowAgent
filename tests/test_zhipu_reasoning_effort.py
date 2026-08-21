import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

fake_zai = types.ModuleType("zai")
fake_zai.ZhipuAiClient = object
sys.modules["zai"] = fake_zai


def test_zhipu_call_with_tools_forwards_reasoning_effort(monkeypatch):
    from models.zhipuai.zhipuai_bot import ZHIPUAIBot

    captured = {}
    bot = ZHIPUAIBot.__new__(ZHIPUAIBot)
    bot.args = {"model": "glm-5.2", "temperature": 0.9, "top_p": 0.7}

    monkeypatch.setattr(bot, "_convert_messages_to_zhipu_format", lambda messages: messages)
    monkeypatch.setattr(bot, "_convert_tools_to_zhipu_format", lambda tools: tools)

    def fake_handle_sync_response(request_params):
        captured.update(request_params)
        return {"content": "ok"}

    monkeypatch.setattr(bot, "_handle_sync_response", fake_handle_sync_response)

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        model="glm-5.2",
        thinking={"type": "enabled"},
        reasoning_effort="xhigh",
    )

    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "xhigh"


def test_zhipu_call_with_tools_omits_reasoning_effort_when_thinking_disabled(monkeypatch):
    from models.zhipuai.zhipuai_bot import ZHIPUAIBot

    captured = {}
    bot = ZHIPUAIBot.__new__(ZHIPUAIBot)
    bot.args = {"model": "glm-5.2", "temperature": 0.9, "top_p": 0.7}

    monkeypatch.setattr(bot, "_convert_messages_to_zhipu_format", lambda messages: messages)
    monkeypatch.setattr(bot, "_convert_tools_to_zhipu_format", lambda tools: tools)

    def fake_handle_sync_response(request_params):
        captured.update(request_params)
        return {"content": "ok"}

    monkeypatch.setattr(bot, "_handle_sync_response", fake_handle_sync_response)

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        model="glm-5.2",
        thinking={"type": "disabled"},
        reasoning_effort="max",
    )

    assert captured["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured


def test_zhipu_glm53_forces_enabled_thinking_even_when_disabled(monkeypatch):
    """GLM-5.3 always thinks; a "disabled" toggle must be upgraded to "enabled"
    with a valid reasoning_effort, otherwise the API returns error 1210."""
    from models.zhipuai.zhipuai_bot import ZHIPUAIBot

    captured = {}
    bot = ZHIPUAIBot.__new__(ZHIPUAIBot)
    bot.args = {"model": "glm-5.3", "temperature": 0.9, "top_p": 0.7}

    monkeypatch.setattr(bot, "_convert_messages_to_zhipu_format", lambda messages: messages)
    monkeypatch.setattr(bot, "_convert_tools_to_zhipu_format", lambda tools: tools)

    def fake_handle_sync_response(request_params):
        captured.update(request_params)
        return {"content": "ok"}

    monkeypatch.setattr(bot, "_handle_sync_response", fake_handle_sync_response)

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        model="glm-5.3",
        thinking={"type": "disabled"},
        reasoning_effort="max",
    )

    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "max"


def test_zhipu_glm53_defaults_effort_when_missing(monkeypatch):
    """GLM-5.3 without any thinking/effort still gets enabled thinking + max."""
    from models.zhipuai.zhipuai_bot import ZHIPUAIBot

    captured = {}
    bot = ZHIPUAIBot.__new__(ZHIPUAIBot)
    bot.args = {"model": "glm-5.3", "temperature": 0.9, "top_p": 0.7}

    monkeypatch.setattr(bot, "_convert_messages_to_zhipu_format", lambda messages: messages)
    monkeypatch.setattr(bot, "_convert_tools_to_zhipu_format", lambda tools: tools)

    def fake_handle_sync_response(request_params):
        captured.update(request_params)
        return {"content": "ok"}

    monkeypatch.setattr(bot, "_handle_sync_response", fake_handle_sync_response)

    bot.call_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        model="glm-5.3",
    )

    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "max"
