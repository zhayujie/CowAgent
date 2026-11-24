"""LinkAI vision defaults to deepseek-flash unless the user pins a model."""

from agent.tools.vision import vision as vision_module
from agent.tools.vision.vision import Vision
from common import const


def _linkai_conf(monkeypatch, **extra):
    values = {"linkai_api_key": "Link_test", **extra}
    monkeypatch.setattr(vision_module, "conf", lambda: values)
    monkeypatch.setattr("common.utils.get_cloud_headers", lambda key: {})


def test_linkai_uses_deepseek_flash_by_default(monkeypatch):
    _linkai_conf(monkeypatch)
    provider = Vision()._build_linkai_provider()
    assert provider.model_override == const.DEEPSEEK_FLASH


def test_linkai_honors_user_pinned_model(monkeypatch):
    _linkai_conf(monkeypatch)
    provider = Vision()._build_linkai_provider("gpt-5.4-mini")
    assert provider.model_override == "gpt-5.4-mini"


def test_use_linkai_auto_chain_starts_with_deepseek_flash(monkeypatch):
    _linkai_conf(monkeypatch, use_linkai=True)
    providers = Vision()._resolve_providers()
    assert providers[0].name == "LinkAI"
    assert providers[0].model_override == const.DEEPSEEK_FLASH


def _hint(model):
    from channel.web.api.models import ModelsHandler

    return ModelsHandler._predict_vision_auto({
        "use_linkai": True, "linkai_api_key": "Link_0123456789abcdef", "model": model,
    })


def test_use_linkai_hint_names_a_vision_capable_main_model():
    assert _hint("claude-sonnet-5") == {"provider": "linkai", "model": "claude-sonnet-5"}
    assert _hint(const.DEEPSEEK_FLASH) == {"provider": "linkai", "model": const.DEEPSEEK_FLASH}


def test_use_linkai_hint_falls_back_for_a_text_only_main_model():
    assert _hint(const.DEEPSEEK_V4_PRO) == {"provider": "linkai", "model": const.DEEPSEEK_FLASH}


def test_linkai_vision_rule_survives_a_missing_vendor_module(monkeypatch):
    import importlib

    from models.linkai.link_ai_bot import LinkAIBot

    real = importlib.import_module

    def fake(name, *args, **kwargs):
        if name == "models.dashscope.dashscope_bot":
            raise ImportError("no dashscope")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake)
    assert LinkAIBot.model_supports_vision("qwen3.8-flash") is None
