"""Exercise MiniMax through requests' serialized, credential-free HTTP boundary."""
import io
import json
from copy import deepcopy

import pytest
import requests

from bridge.context import Context, ContextType
from common import const
from models.minimax import minimax_bot


@pytest.fixture
def transport(monkeypatch):
    sent = []
    replies = []

    def send(_session, request, **kwargs):
        sent.append((request.url, json.loads(request.body)))
        response = requests.Response()
        response.status_code = 200
        message = replies.pop(0) if replies else {"content": "ok", "reasoning_content": "Think carefully."}
        finish_reason = "tool_calls" if message.get("tool_calls") else "stop"
        body = {"choices": [{"message": message, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
        if kwargs.get("stream"):
            body = {"choices": [{"delta": message, "finish_reason": "stop"}]}
            response.raw = io.BytesIO(("data: " + json.dumps(body) + "\n\ndata: [DONE]\n\n").encode())
        else:
            response._content = json.dumps(body).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return sent, replies


@pytest.mark.parametrize("base", ["https://api.minimaxi.com/v1", "https://api.minimax.cn/v1", "https://api.minimax.io/v1"])
@pytest.mark.parametrize("model", [None, "MiniMax-M3", "MiniMax-M2.7", "saved-custom-model"])
def test_default_and_saved_models_reach_http_and_keep_chat_thinking(monkeypatch, transport, base, model):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {"model": model, "minimax_api_base": base})
    bot = minimax_bot.MinimaxBot()
    context = Context(ContextType.TEXT, "hello", {"session_id": "chat"})
    assert bot.reply("hello", context).content == "ok"
    bot.reply("continue", context)
    sent, _ = transport
    assert sent[0][0] == base + "/chat/completions"
    assert sent[0][1]["model"] == (model or const.MINIMAX_M3_1_FLASH)
    assert sent[1][1]["messages"][-2]["reasoning_content"] == "Think carefully."
    assert "thinking" not in sent[0][1]
    assert "reasoning_effort" not in sent[0][1]
    assert "service_tier" not in sent[0][1]


@pytest.mark.parametrize("stream", [False, True])
def test_tool_roundtrip_preserves_thinking_images_and_tool_ids(monkeypatch, transport, stream):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {})
    bot = minimax_bot.MinimaxBot()
    sent, replies = transport
    tool_call = {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": '{"q":"test"}'}}
    replies.append({"content": None, "reasoning_content": "Need a lookup.", "tool_calls": [tool_call]})
    image = {"role": "user", "content": [{"type": "text", "text": "Describe"},
             {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
             {"type": "video_url", "video_url": {"url": "mm_file://fixture"}}]}
    tools = [{"name": "lookup", "description": "Look up", "input_schema": {"type": "object"}}]
    first = list(bot.call_with_tools([image], tools=tools))[-1]
    assert first["content"][0] == {"type": "thinking", "thinking": "Need a lookup."}
    history = [image, first, {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "call_1", "content": "found"}]}]
    original = deepcopy(history)
    result = list(bot.call_with_tools(history, tools=tools, stream=stream, reasoning_effort="high"))
    payload = sent[-1][1]
    assert payload["model"] == const.MINIMAX_M3_1_FLASH
    assert payload["messages"][0] == image
    assert payload["messages"][1]["reasoning_content"] == "Need a lookup."
    replayed = payload["messages"][1]["tool_calls"][0]
    assert replayed["id"] == tool_call["id"]
    assert replayed["function"]["name"] == "lookup"
    assert json.loads(replayed["function"]["arguments"]) == {"q": "test"}
    assert payload["messages"][2] == {"role": "tool", "tool_call_id": "call_1", "content": "found"}
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert payload["reasoning_split"] is True
    assert payload["reasoning_effort"] == "high"
    assert history == original
    if stream:
        assert any(c.get("choices", [{}])[0].get("delta", {}).get("reasoning_content") == "Think carefully."
                   for c in result)
    else:
        assert result[0]["content"][0]["thinking"] == "Think carefully."


def test_native_history_is_replayed_without_loss(monkeypatch, transport):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {})
    history = [{"role": "system", "content": "System"}, {"role": "user", "content": "Hello"},
               {"role": "assistant", "content": "<think>Keep tags</think>", "reasoning_content": "Keep reasoning",
                "reasoning_details": [{"text": "Legacy reasoning"}], "tool_calls": [{"id": "c", "type": "function",
                 "function": {"name": "lookup", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "c", "content": "done"}]
    list(minimax_bot.MinimaxBot().call_with_tools(history))
    assert transport[0][0][1]["messages"] == history


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_flash_efforts(monkeypatch, transport, effort):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {})
    list(minimax_bot.MinimaxBot().call_with_tools([], thinking={"type": "adaptive"}, reasoning_effort=effort))
    assert transport[0][0][1]["thinking"] == {"type": "adaptive"}
    assert transport[0][0][1]["reasoning_effort"] == effort


@pytest.mark.parametrize("kwargs", [{"thinking": {"type": "disabled"}}, {"reasoning_effort": "none"}])
def test_flash_rejects_incompatible_thinking_before_http(monkeypatch, transport, kwargs):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {})
    assert list(minimax_bot.MinimaxBot().call_with_tools([], **kwargs))[0]["error"]
    assert transport[0] == []


def test_m3_can_disable_thinking_and_explicit_model_override_survives(monkeypatch, transport):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {})
    list(minimax_bot.MinimaxBot().call_with_tools([], model=const.MINIMAX_M3, thinking={"type": "disabled"}))
    assert transport[0][0][1]["model"] == const.MINIMAX_M3
    assert transport[0][0][1]["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("model", [const.MINIMAX_M3_1_FLASH, const.MINIMAX_M3])
def test_native_vision_http_keeps_selected_model(monkeypatch, transport, model):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {"model": model})
    bot = minimax_bot.MinimaxBot()
    assert bot.supports_vision
    assert bot.call_vision("https://example.invalid/image.png", "Describe")["content"] == "ok"
    payload = transport[0][0][1]
    assert payload["model"] == model
    assert payload["messages"][0]["content"][1]["image_url"]["url"] == "https://example.invalid/image.png"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("thinking_enabled", [False, True])
def test_agent_default_reaches_http_with_adaptive_thinking(monkeypatch, transport, stream, thinking_enabled):
    import config
    from bridge import agent_bridge
    from agent.protocol import LLMRequest

    settings = {"bot_type": "minimax", "enable_thinking": thinking_enabled,
                "reasoning_effort_by_model": {"minimax:minimax-m3.1-flash": "max"}}
    monkeypatch.setattr(config, "conf", lambda: settings)
    monkeypatch.setattr(agent_bridge, "conf", lambda: settings)
    monkeypatch.setattr(minimax_bot, "conf", lambda: settings)
    model = agent_bridge.AgentLLMModel(None)
    request = LLMRequest(messages=[{"role": "user", "content": "Hello"}])
    list(model.call_stream(request) if stream else model.call(request))
    payload = transport[0][0][1]
    assert payload["model"] == const.MINIMAX_M3_1_FLASH
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["reasoning_effort"] == "max"
    assert "service_tier" not in payload
    from agent.protocol.agent import resolve_family_spec
    assert resolve_family_spec(model.model) == (1000000, 524288)


def test_legacy_agent_options_remain_unsent(monkeypatch, transport):
    monkeypatch.setattr(minimax_bot, "conf", lambda: {"model": const.MINIMAX_M2_7})
    list(minimax_bot.MinimaxBot().call_with_tools([], thinking={"type": "enabled"}, reasoning_effort="medium"))
    payload = transport[0][0][1]
    assert payload["model"] == const.MINIMAX_M2_7
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


def test_non_minimax_default_is_unchanged(monkeypatch):
    from bridge import agent_bridge
    monkeypatch.setattr(agent_bridge, "conf", lambda: {})
    assert agent_bridge.AgentLLMModel(None).model == const.DEFAULT_MODEL


def test_picker_defaults_and_saved_catalog_overrides(monkeypatch):
    from channel.web.api.models import ModelsHandler
    from channel.web.core.providers import PROVIDER_MODELS

    assert PROVIDER_MODELS["minimax"]["models"] == [const.MINIMAX_M3_1_FLASH, const.MINIMAX_M3]
    assert [m for m in PROVIDER_MODELS["linkai"]["models"] if m.startswith("MiniMax")] == [const.MINIMAX_M3]
    catalog = ModelsHandler._merged_catalog("minimax", catalog_map={}, hidden_map={})
    assert [e["name"] for e in catalog if "text" in e["capabilities"]] == [const.MINIMAX_M3_1_FLASH, const.MINIMAX_M3]
    assert catalog[0]["context_window"] == 1000000
    assert catalog[0]["max_output_tokens"] == 524288
    saved = {"name": "MiniMax-M2.7", "capabilities": ["text"], "context_window": 12345}
    catalog = ModelsHandler._merged_catalog("minimax", catalog_map={"minimax": [saved]}, hidden_map={})
    assert saved in catalog
    assert ModelsHandler._merged_catalog("custom", catalog_map={"custom": [saved]}, hidden_map={}) == [saved]
    # MODEL_LIST is the explicit #model command validator, not the UI preset list.
    assert const.MINIMAX_M2_7 in const.MODEL_LIST
    assert const.MINIMAX_M3_1_FLASH in const.MODEL_LIST
