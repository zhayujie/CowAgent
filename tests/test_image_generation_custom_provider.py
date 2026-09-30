import importlib.util
import json
import os
from pathlib import Path

from config import sync_image_generation_custom_provider_env

SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "skills"
    / "image-generation"
    / "scripts"
    / "generate.py"
)
SPEC = importlib.util.spec_from_file_location(
    "image_generation_script",
    SCRIPT_PATH,
)
image_generation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_generation)


def _config():
    return {
        "custom_providers": [
            {
                "id": "image_vendor",
                "name": "image-vendor",
                "api_key": "image-key",
                "api_base": "https://images.example.com/v1",
                "model": "vendor-image-model",
            },
        ],
        "skills": {
            "image-generation": {
                "provider": "custom:image_vendor",
                "model": "vendor-image-model",
            },
        },
    }


def test_sync_selected_custom_image_provider_to_env(monkeypatch):
    monkeypatch.delenv(
        "SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER",
        raising=False,
    )

    assert sync_image_generation_custom_provider_env(_config()) == 1

    payload = json.loads(
        os.environ["SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER"]
    )
    assert payload == {
        "id": "image_vendor",
        "name": "image-vendor",
        "api_key": "image-key",
        "api_base": "https://images.example.com/v1",
        "model": "vendor-image-model",
    }


def test_build_providers_uses_explicit_custom_provider(monkeypatch):
    monkeypatch.setenv(
        "SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER",
        json.dumps(_config()["custom_providers"][0]),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")

    providers = image_generation._build_providers(
        "vendor-image-model",
        provider_id="custom:image_vendor",
    )

    assert len(providers) == 1
    label, provider = providers[0]
    assert label == "image-vendor"
    assert isinstance(provider, image_generation.OpenAIProvider)
    assert provider.api_key == "image-key"
    assert provider.api_base == "https://images.example.com/v1"
    assert provider.model == "vendor-image-model"


def _only_aggregator_key(monkeypatch):
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ARK_API_KEY",
                 "DASHSCOPE_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LINKAI_API_KEY", "aggregator-key")


def test_build_providers_keeps_pinned_model_on_aggregator(monkeypatch):
    _only_aggregator_key(monkeypatch)

    for requested, expected in (
        ("gpt-image-2.5-flare", "gpt-image-2.5-flare"),
        ("nano-banana-pro", "gemini-3-pro-image-preview"),
    ):
        providers = image_generation._build_providers(requested)
        assert [p.model for _, p in providers] == [expected]


def test_build_providers_drops_model_aggregator_does_not_serve(monkeypatch):
    _only_aggregator_key(monkeypatch)

    providers = image_generation._build_providers("qwen-image-2.0")

    assert [p.model for _, p in providers] == [
        image_generation.LinkAIProvider.DEFAULT_MODEL,
    ]


def test_build_providers_does_not_fallback_for_missing_custom_provider(
    monkeypatch,
):
    monkeypatch.delenv(
        "SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER",
        raising=False,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")

    providers = image_generation._build_providers(
        "vendor-image-model",
        provider_id="custom:missing",
    )

    assert providers == []
