"""
Regression coverage for the "AI/ML API model id misroutes to the native
vendor provider" bug (caught in code review). AI/ML API model ids are
namespaced "<vendor>/<model>" (e.g. "deepseek/deepseek-v4-pro-0813"), which
collides with several bare vendor-prefix inference rules used, in different
places, whenever bot_type is empty and the provider must be derived from the
model name alone. Each fix site gets its own direct test here; the
web_channel.py / bridge.py sites already have coverage in
tests/test_models_handler.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    from plugins.cow_cli.cow_cli import KNOWN_COMMANDS  # noqa: F401 - import registers the plugin
finally:
    plugins.instance.current_plugin_path = _old_plugin_path


def test_agent_llm_model_resolves_aimlapi_not_native_deepseek(monkeypatch):
    from bridge.agent_bridge import AgentLLMModel
    from config import conf

    monkeypatch.setitem(conf(), "use_linkai", False)
    monkeypatch.setitem(conf(), "bot_type", "")

    model = AgentLLMModel(None)
    assert model._resolve_bot_type("deepseek/deepseek-v4-pro-0813") == "aimlapi"


def test_agent_llm_model_resolves_aimlapi_not_openai_fallback(monkeypatch):
    """anthropic/claude-opus-5 matches no bare-prefix rule at all (no leading
    "claude"), so before the fix it silently fell through to the default
    OpenAI provider — just as wrong as misrouting to a matching vendor."""
    from bridge.agent_bridge import AgentLLMModel
    from config import conf

    monkeypatch.setitem(conf(), "use_linkai", False)
    monkeypatch.setitem(conf(), "bot_type", "")

    model = AgentLLMModel(None)
    assert model._resolve_bot_type("anthropic/claude-opus-5") == "aimlapi"


def test_cow_cli_resolves_aimlapi_not_native_deepseek():
    CowCliPlugin = plugins.instance.plugins["COW_CLI"]
    assert CowCliPlugin._resolve_bot_type_for_model("deepseek/deepseek-v4-pro-0813") == "aimlapi"


def test_gpt5_reasoning_model_recognizes_aimlapi_namespaced_id():
    from models.openai_compatible_bot import OpenAICompatibleBot

    assert OpenAICompatibleBot._is_gpt5_reasoning_model("openai/gpt-5-5") is True
    assert OpenAICompatibleBot._is_gpt5_reasoning_model("openai/o3-mini") is True
    # A non-reasoning AI/ML API model must still read as False.
    assert OpenAICompatibleBot._is_gpt5_reasoning_model("deepseek/deepseek-v4-pro-0813") is False
