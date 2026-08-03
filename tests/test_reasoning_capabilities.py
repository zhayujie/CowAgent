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


def test_claude_5_models_expose_all_effort_values():
    cap = get_reasoning_capability("claudeAPI", "claude-opus-5")

    assert cap["supported"] is True
    assert cap["param"] == "effort"
    assert cap["default"] == "high"
    assert _values(cap) == ["low", "medium", "high", "xhigh", "max"]


def test_claude_4_6_models_hide_xhigh_effort():
    cap = get_reasoning_capability("claudeAPI", "claude-sonnet-4-6")

    assert cap["supported"] is True
    assert cap["param"] == "effort"
    assert cap["default"] == "high"
    assert _values(cap) == ["low", "medium", "high", "max"]


def test_older_claude_models_hide_effort_control():
    assert get_reasoning_capability("claudeAPI", "claude-sonnet-4-0") == {"supported": False, "options": []}
    assert get_reasoning_capability("claudeAPI", "claude-3-5-sonnet-latest") == {"supported": False, "options": []}


def test_dashscope_qwen38_max_exposes_native_effort_values():
    cap = get_reasoning_capability("dashscope", "qwen3.8-max-preview")

    assert cap["supported"] is True
    assert cap["param"] == "reasoning_effort"
    assert cap["default"] == "xhigh"
    assert cap["thinking_only"] is True
    assert _values(cap) == ["low", "medium", "xhigh"]
    assert get_reasoning_capability("dashscope", "qwen3.8-max") == {"supported": False, "options": []}


def test_dashscope_direct_glm_and_deepseek_expose_high_max_effort_values():
    glm_cap = get_reasoning_capability("dashscope", "glm-5.2")
    deepseek_cap = get_reasoning_capability("dashscope", "deepseek-v4-flash")

    assert glm_cap["supported"] is True
    assert glm_cap["default"] == "high"
    assert _values(glm_cap) == ["high", "max"]
    assert deepseek_cap["supported"] is True
    assert _values(deepseek_cap) == ["high", "max"]


def test_dashscope_kimi_k3_only_exposes_max_effort():
    cap = get_reasoning_capability("dashscope", "kimi/kimi-k3")

    assert cap["supported"] is True
    assert cap["default"] == "max"
    assert _values(cap) == ["max"]


def test_dashscope_other_qwen_models_hide_effort_control():
    assert get_reasoning_capability("dashscope", "qwen3.7-plus") == {"supported": False, "options": []}


def test_kimi_k3_exposes_low_high_max_effort_values():
    cap = get_reasoning_capability("moonshot", "kimi-k3")

    assert cap["supported"] is True
    assert cap["param"] == "reasoning_effort"
    assert cap["default"] == "max"
    assert cap["thinking_only"] is True
    assert _values(cap) == ["low", "high", "max"]


def test_kimi_k2_models_hide_effort_control():
    assert get_reasoning_capability("moonshot", "kimi-k2.7-code") == {"supported": False, "options": []}
    assert get_reasoning_capability("moonshot", "kimi-k2.6") == {"supported": False, "options": []}


def test_linkai_exposes_known_passthrough_effort_models():
    deepseek_cap = get_reasoning_capability("linkai", "deepseek-v4-flash")
    glm_cap = get_reasoning_capability("linkai", "glm-5.2")
    kimi_cap = get_reasoning_capability("linkai", "kimi-k3")

    assert deepseek_cap["supported"] is True
    assert deepseek_cap["default"] == "high"
    assert _values(deepseek_cap) == ["high", "max"]
    assert glm_cap["supported"] is True
    assert glm_cap["default"] == "high"
    assert _values(glm_cap) == ["low", "medium", "high", "xhigh", "max"]
    assert kimi_cap["supported"] is True
    assert kimi_cap["default"] == "max"
    assert kimi_cap["thinking_only"] is True
    assert _values(kimi_cap) == ["low", "high", "max"]


def test_linkai_hides_unsupported_or_unverified_passthrough_models():
    assert get_reasoning_capability("linkai", "gpt-5.4") == {"supported": False, "options": []}
    assert get_reasoning_capability("linkai", "qwen3.8-max-preview") == {"supported": False, "options": []}
    assert get_reasoning_capability("linkai", "claude-opus-5") == {"supported": False, "options": []}


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
    assert normalize_reasoning_effort("claudeAPI", "claude-opus-5", "xhigh") == "xhigh"
    assert normalize_reasoning_effort("claudeAPI", "claude-sonnet-4-6", "xhigh") == "high"
    assert normalize_reasoning_effort("dashscope", "qwen3.8-max", "high") is None
    assert normalize_reasoning_effort("dashscope", "qwen3.8-max-preview", "minimal") == "low"
    assert normalize_reasoning_effort("dashscope", "glm-5.2", "low") == "high"
    assert normalize_reasoning_effort("dashscope", "deepseek-v4-pro", "xhigh") == "max"
    assert normalize_reasoning_effort("dashscope", "kimi/kimi-k3", "high") == "max"
    assert normalize_reasoning_effort("moonshot", "kimi-k3", "low") == "low"
    assert normalize_reasoning_effort("moonshot", "kimi-k3", "medium") == "max"
    assert normalize_reasoning_effort("linkai", "deepseek-v4-flash", "low") == "high"
    assert normalize_reasoning_effort("linkai", "deepseek-v4-flash", "xhigh") == "max"
    assert normalize_reasoning_effort("linkai", "glm-5.2", "medium") == "medium"
    assert normalize_reasoning_effort("linkai", "glm-5.2", "minimal") == "high"
    assert normalize_reasoning_effort("linkai", "kimi-k3", "medium") == "max"
    assert normalize_reasoning_effort("linkai", "gpt-5.4", "high") is None
    assert normalize_reasoning_effort("gemini", "gemini-3.5-flash", "high") is None
