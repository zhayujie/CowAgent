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
