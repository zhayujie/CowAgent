import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.setdefault("regex", re)


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


def _model_with_bot(monkeypatch, bot_type, model_name):
    from bridge.agent_bridge import AgentLLMModel
    from config import conf

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
