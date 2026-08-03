import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.reasoning_capabilities import (
    get_reasoning_capability,
    normalize_reasoning_effort,
)


def _values(capability):
    return [item["value"] for item in capability["options"]]


def test_deepseek_exposes_native_effort_values():
    cap = get_reasoning_capability("deepseek", "deepseek-v4-flash")

    assert cap["supported"] is True
    assert cap["param"] == "reasoning_effort"
    assert cap["default"] == "high"
    assert _values(cap) == ["low", "high", "xhigh", "max"]


def test_deepseek_non_v4_models_hide_effort_control():
    assert get_reasoning_capability("deepseek", "deepseek-chat") == {"supported": False, "options": []}
    assert get_reasoning_capability("deepseek", "deepseek-reasoner") == {"supported": False, "options": []}


def test_zhipu_exposes_native_effort_values_without_disable_aliases():
    cap = get_reasoning_capability("zhipu", "glm-5.2")

    assert cap["supported"] is True
    assert cap["param"] == "reasoning_effort"
    assert cap["default"] == "high"
    assert _values(cap) == ["low", "medium", "high", "xhigh", "max"]


def test_openai_is_hidden_until_responses_api_runtime_support_exists():
    cap = get_reasoning_capability("openai", "gpt-5.4")

    assert cap == {"supported": False, "options": []}


def test_custom_provider_is_hidden_by_default():
    cap = get_reasoning_capability("custom:local", "provider-native-model")

    assert cap == {"supported": False, "options": []}


def test_unsupported_provider_returns_hidden_capability():
    cap = get_reasoning_capability("gemini", "gemini-3.5-flash")

    assert cap == {"supported": False, "options": []}


def test_normalize_returns_provider_default_for_invalid_value():
    assert normalize_reasoning_effort("deepseek", "deepseek-v4-flash", "medium") == "high"
    assert normalize_reasoning_effort("deepseek", "deepseek-v4-flash", "low") == "low"
    assert normalize_reasoning_effort("deepseek", "deepseek-v4-flash", "xhigh") == "xhigh"
    assert normalize_reasoning_effort("deepseek", "deepseek-v4-flash", "max") == "max"
    assert normalize_reasoning_effort("zhipu", "glm-5.2", "minimal") == "high"
    assert normalize_reasoning_effort("zhipu", "glm-5.2", "medium") == "medium"
    assert normalize_reasoning_effort("gemini", "gemini-3.5-flash", "high") is None
