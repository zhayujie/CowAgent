"""Routing and default-model tests for the image-generation skill.

Covers the gpt-image-2.x families: the ids must resolve to the OpenAI
provider, the recommended default must be gpt-image-2.6-flare on both the
OpenAI and LinkAI backends, and gpt-image-2.6 must default to high quality.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "skills"
    / "image-generation"
    / "scripts"
    / "generate.py"
)
SPEC = importlib.util.spec_from_file_location(
    "image_generation_routing_script",
    SCRIPT_PATH,
)
image_generation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_generation)


@pytest.mark.parametrize(
    "model",
    [
        "gpt-image-2.6-flare",
        "gpt-image-2.6-sunburst",
        "gpt-image-2.5-flare",
        "gpt-image-2.5-sunburst",
        "gpt-image-2.5-flare-2026-09-09",
        "GPT-Image-2.5-Flare",
        "gpt-image-2",
        "gpt-image-1",
    ],
)
def test_gpt_image_models_route_to_openai(model):
    assert image_generation._preferred_provider(model) == "OpenAI"


def test_unknown_prefix_has_no_preferred_provider():
    assert image_generation._preferred_provider("some-other-model") is None


def test_openai_default_model_is_recommended_flare():
    assert image_generation.OpenAIProvider.DEFAULT_MODEL == "gpt-image-2.6-flare"


def test_linkai_default_model_is_recommended_flare():
    assert image_generation.LinkAIProvider.DEFAULT_MODEL == "gpt-image-2.6-flare"


def test_explicit_model_overrides_default():
    provider = image_generation.OpenAIProvider(
        api_key="k",
        api_base="https://api.openai.com/v1",
        model="gpt-image-2.5-sunburst",
    )
    assert provider.model == "gpt-image-2.5-sunburst"


def test_empty_model_falls_back_to_default():
    provider = image_generation.OpenAIProvider(
        api_key="k",
        api_base="https://api.openai.com/v1",
        model="",
    )
    assert provider.model == "gpt-image-2.6-flare"


@pytest.mark.parametrize(
    "model, quality, expected",
    [
        ("gpt-image-2.6-flare", None, "high"),
        ("GPT-Image-2.6-Sunburst", None, "high"),
        ("gpt-image-2.6-flare", "low", "low"),
        ("gpt-image-2.5-flare", None, None),
        ("gemini-nano-banana-2.1", None, None),
    ],
)
def test_default_quality(model, quality, expected):
    assert image_generation._default_quality(model, quality) == expected


def test_openai_provider_sends_high_quality_by_default(monkeypatch):
    provider = image_generation.OpenAIProvider(
        api_key="k",
        api_base="https://api.openai.com/v1",
        model="",
    )
    sent = {}

    def fake_create(prompt, *, quality, size, output_dir):
        sent["quality"] = quality
        return ["/tmp/out.png"]

    monkeypatch.setattr(provider, "_create", fake_create)
    provider.generate("a cat")
    assert sent["quality"] == "high"
