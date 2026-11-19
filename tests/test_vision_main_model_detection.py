"""Main-model vision detection honors catalog ticks and gateway-prefixed names."""

from types import SimpleNamespace

import pytest

from agent.tools.vision.vision import Vision


def _vision(model, caps=None):
    tool = Vision()
    tool.model = SimpleNamespace(
        model=model,
        catalog_model_meta=lambda: {"name": model, "capabilities": caps} if caps else {},
    )
    return tool


class _Bot:
    pass


@pytest.mark.parametrize("model", ["openai/gpt-4o", "global:gpt-4o", "cn:doubao-seed-1.6"])
def test_gateway_prefix_is_ignored_for_the_name_match(model):
    assert _vision(model)._main_bot_supports_vision(_Bot())


def test_unknown_model_still_needs_a_declaration():
    assert not _vision("my-gateway-model")._main_bot_supports_vision(_Bot())


def test_catalog_vision_tick_is_trusted_for_custom_models():
    assert _vision("my-gateway-model", ["text", "vision"])._main_bot_supports_vision(_Bot())


def test_catalog_tick_overrides_a_bot_that_says_no_but_text_only_is_no_verdict():
    bot = SimpleNamespace(supports_vision=False)
    assert _vision("deepseek-chat", ["text", "vision"])._main_bot_supports_vision(bot)
    assert not _vision("deepseek-chat", ["text"])._main_bot_supports_vision(bot)
    assert _vision("gpt-4o", ["text"])._main_bot_supports_vision(_Bot())


def test_the_agent_model_is_checked_not_the_global_config_model(monkeypatch):
    from config import conf
    from models.deepseek.deepseek_bot import DeepSeekBot

    monkeypatch.setitem(conf(), "model", "claude-opus-5-5")
    bot = DeepSeekBot.__new__(DeepSeekBot)
    assert _vision("deepseek-flash")._main_bot_supports_vision(bot)
    assert not _vision("deepseek-v4-pro")._main_bot_supports_vision(bot)
