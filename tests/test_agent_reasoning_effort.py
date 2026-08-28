import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _Bot:
    def __init__(self):
        self.kwargs = None

    def call_with_tools(self, **kwargs):
        self.kwargs = kwargs
        return {"content": "ok"}


class _Request:
    messages = [{"role": "user", "content": "hi"}]
    tools = []
    max_tokens = None
    system = None


def _model_with_bot(monkeypatch, bot_type, model_name, use_linkai=False):
    from bridge.agent_bridge import AgentLLMModel
    from config import conf

    monkeypatch.setitem(conf(), "use_linkai", use_linkai)
    monkeypatch.setitem(conf(), "linkai_api_key", "test-key" if use_linkai else "")
    monkeypatch.setitem(conf(), "bot_type", bot_type)
    monkeypatch.setitem(conf(), "model", model_name)

    model = AgentLLMModel(None)
    bot = _Bot()
    model._bot = bot
    model._bot_model = model_name
    model._bot_type = model._resolve_bot_type(model_name)
    return model, bot


def test_agent_bridge_passes_deepseek_native_max(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "max")
    model, bot = _model_with_bot(monkeypatch, "deepseek", "deepseek-v4-flash")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert bot.kwargs["reasoning_effort"] == "max"


def test_agent_bridge_passes_deepseek_native_xhigh(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "xhigh")
    model, bot = _model_with_bot(monkeypatch, "deepseek", "deepseek-v4-flash")

    model.call(_Request())

    assert bot.kwargs["reasoning_effort"] == "xhigh"


def test_agent_bridge_passes_zhipu_native_medium(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "medium")
    model, bot = _model_with_bot(monkeypatch, "zhipu", "glm-5.2")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert bot.kwargs["reasoning_effort"] == "medium"


def test_agent_bridge_passes_claude_native_xhigh(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "xhigh")
    model, bot = _model_with_bot(monkeypatch, "claudeAPI", "claude-opus-5")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert bot.kwargs["reasoning_effort"] == "xhigh"


def test_agent_bridge_defaults_invalid_claude_value(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "xhigh")
    model, bot = _model_with_bot(monkeypatch, "claudeAPI", "claude-sonnet-4-6")

    model.call(_Request())

    assert bot.kwargs["reasoning_effort"] == "high"


def test_agent_bridge_omits_claude_effort_when_thinking_disabled(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", False)
    monkeypatch.setitem(conf(), "reasoning_effort", "max")
    model, bot = _model_with_bot(monkeypatch, "claudeAPI", "claude-opus-5")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in bot.kwargs


def test_agent_bridge_passes_dashscope_qwen38_effort(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "medium")
    model, bot = _model_with_bot(monkeypatch, "dashscope", "qwen3.8-max")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert bot.kwargs["reasoning_effort"] == "medium"


def test_agent_bridge_maps_dashscope_qwen38_high_to_xhigh(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "high")
    model, bot = _model_with_bot(monkeypatch, "dashscope", "qwen3.8-max")

    model.call(_Request())

    assert bot.kwargs["reasoning_effort"] == "xhigh"


def test_agent_bridge_forces_dashscope_qwen38_thinking(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", False)
    monkeypatch.setitem(conf(), "reasoning_effort", "medium")
    model, bot = _model_with_bot(monkeypatch, "dashscope", "qwen3.8-max")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert bot.kwargs["reasoning_effort"] == "medium"


def test_agent_bridge_forces_kimi_k3_thinking(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", False)
    monkeypatch.setitem(conf(), "reasoning_effort", "low")
    model, bot = _model_with_bot(monkeypatch, "moonshot", "kimi-k3")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert bot.kwargs["reasoning_effort"] == "low"


def test_agent_bridge_passes_linkai_deepseek_passthrough_effort(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "xhigh")
    model, bot = _model_with_bot(monkeypatch, "openai", "deepseek-v4-flash", use_linkai=True)

    model.call(_Request())

    assert model._resolve_bot_type("deepseek-v4-flash") == "linkai"
    assert bot.kwargs["thinking"] == {"type": "enabled"}
    # deepseek-v4 takes the value as-is through the gateway; the upstream maps
    # it to its own level.
    assert bot.kwargs["reasoning_effort"] == "xhigh"


def test_agent_bridge_passes_linkai_glm_passthrough_effort(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "medium")
    model, bot = _model_with_bot(monkeypatch, "openai", "glm-5.2", use_linkai=True)

    model.call(_Request())

    assert model._resolve_bot_type("glm-5.2") == "linkai"
    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert bot.kwargs["reasoning_effort"] == "medium"


def test_agent_bridge_omits_linkai_openai_effort_until_runtime_support_exists(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "high")
    model, bot = _model_with_bot(monkeypatch, "openai", "gpt-5.4", use_linkai=True)

    model.call(_Request())

    assert model._resolve_bot_type("gpt-5.4") == "linkai"
    assert "reasoning_effort" not in bot.kwargs


def test_agent_bridge_defaults_invalid_deepseek_value(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "medium")
    model, bot = _model_with_bot(monkeypatch, "deepseek", "deepseek-v4-flash")

    model.call(_Request())

    assert bot.kwargs["reasoning_effort"] == "high"


def test_agent_bridge_omits_openai_effort_until_runtime_support_exists(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "high")
    model, bot = _model_with_bot(monkeypatch, "openai", "gpt-5.4")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in bot.kwargs


def test_agent_bridge_omits_effort_when_thinking_disabled(monkeypatch):
    from config import conf

    monkeypatch.setitem(conf(), "enable_thinking", False)
    monkeypatch.setitem(conf(), "reasoning_effort", "max")
    model, bot = _model_with_bot(monkeypatch, "deepseek", "deepseek-v4-flash")

    model.call(_Request())

    assert bot.kwargs["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in bot.kwargs


def test_agent_bridge_uses_per_model_effort_over_global(monkeypatch):
    from config import conf

    # Global key says "max", but the per-model entry for deepseek-v4-flash
    # says "low" — per-model must win (no remap, no global override).
    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "max")
    monkeypatch.setitem(conf(), "reasoning_effort_by_model", {"deepseek:deepseek-v4-flash": "low"})
    model, bot = _model_with_bot(monkeypatch, "deepseek", "deepseek-v4-flash")

    model.call(_Request())

    assert bot.kwargs["reasoning_effort"] == "low"


def test_agent_bridge_ignores_other_models_per_model_effort(monkeypatch):
    from config import conf

    # Only a *different* model has a per-model entry; the active model falls
    # back to the global value.
    monkeypatch.setitem(conf(), "enable_thinking", True)
    monkeypatch.setitem(conf(), "reasoning_effort", "high")
    monkeypatch.setitem(conf(), "reasoning_effort_by_model", {"claude:claude-opus-5": "max"})
    model, bot = _model_with_bot(monkeypatch, "deepseek", "deepseek-v4-flash")

    model.call(_Request())

    assert bot.kwargs["reasoning_effort"] == "high"


def test_agent_bridge_preserves_thinking_blocks_for_thinking_only_models(monkeypatch):
    from bridge.agent_bridge import AgentBridge
    from config import conf

    captured = {}

    class _Store:
        def append_messages(self, session_id, messages, channel_type="", create_if_missing=True):
            captured["messages"] = messages
            return True

    bridge = AgentBridge.__new__(AgentBridge)
    monkeypatch.setattr(bridge, "get_conversation_store", lambda agent_id=None: _Store())
    monkeypatch.setitem(conf(), "conversation_persistence", True)
    monkeypatch.setitem(conf(), "enable_thinking", False)
    monkeypatch.setitem(conf(), "bot_type", "moonshot")
    monkeypatch.setitem(conf(), "model", "kimi-k3")

    bridge._persist_messages(
        "session-1",
        [{
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "keep me"},
                {"type": "text", "text": "answer"},
            ],
        }],
    )

    assert captured["messages"][0]["content"][0] == {"type": "thinking", "thinking": "keep me"}
