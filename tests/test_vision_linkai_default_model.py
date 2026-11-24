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
