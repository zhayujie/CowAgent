import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.reasoning_capabilities import (
    get_reasoning_capability,
    normalize_reasoning_effort,
    resolve_reasoning_effort,
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
    # qwen3.8-max and its -preview snapshot share the same native effort enum.
    for model in ("qwen3.8-max", "qwen3.8-max-preview"):
        cap = get_reasoning_capability("dashscope", model)

        assert cap["supported"] is True, model
        assert cap["param"] == "reasoning_effort"
        assert cap["default"] == "xhigh"
        assert cap["thinking_only"] is True
        assert _values(cap) == ["low", "medium", "xhigh"]


def test_dashscope_glm_exposes_high_max_effort_values():
    glm_cap = get_reasoning_capability("dashscope", "glm-5.2")

    assert glm_cap["supported"] is True
    assert glm_cap["default"] == "high"
    assert _values(glm_cap) == ["high", "max"]


def test_dashscope_deepseek_keeps_the_model_native_effort_values():
    deepseek_cap = get_reasoning_capability("dashscope", "deepseek-v4-flash")

    assert deepseek_cap["supported"] is True
    assert deepseek_cap["default"] == "high"
    assert _values(deepseek_cap) == ["low", "high", "xhigh", "max"]


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
    assert _values(deepseek_cap) == ["low", "high", "xhigh", "max"]
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
    assert normalize_reasoning_effort("dashscope", "qwen3.8-max", "high") == "xhigh"
    assert normalize_reasoning_effort("dashscope", "qwen3.8-max", "minimal") == "low"
    assert normalize_reasoning_effort("dashscope", "qwen3.8-max-preview", "minimal") == "low"
    assert normalize_reasoning_effort("dashscope", "glm-5.2", "low") == "high"
    assert normalize_reasoning_effort("dashscope", "deepseek-v4-pro", "xhigh") == "xhigh"
    assert normalize_reasoning_effort("dashscope", "deepseek-v4-pro", "low") == "low"
    assert normalize_reasoning_effort("dashscope", "kimi/kimi-k3", "high") == "max"
    assert normalize_reasoning_effort("moonshot", "kimi-k3", "low") == "low"
    assert normalize_reasoning_effort("moonshot", "kimi-k3", "medium") == "max"
    assert normalize_reasoning_effort("linkai", "deepseek-v4-flash", "low") == "low"
    assert normalize_reasoning_effort("linkai", "deepseek-v4-flash", "xhigh") == "xhigh"
    assert normalize_reasoning_effort("linkai", "glm-5.2", "medium") == "medium"
    assert normalize_reasoning_effort("linkai", "glm-5.2", "minimal") == "high"
    assert normalize_reasoning_effort("linkai", "kimi-k3", "medium") == "max"
    assert normalize_reasoning_effort("linkai", "gpt-5.4", "high") is None
    assert normalize_reasoning_effort("gemini", "gemini-3.5-flash", "high") is None


# --- resolve_reasoning_effort (per-model config resolution) ---


def test_resolve_returns_stored_per_model_value_without_rewriting():
    # deepseek-v4 allows low, so a stored "low" is returned verbatim.
    by_model = {"deepseek:deepseek-v4-flash": "low"}
    assert resolve_reasoning_effort("deepseek", "deepseek-v4-flash", by_model, "high") == "low"


def test_resolve_prefers_raw_provider_key_over_base_key():
    # Raw provider id ("claudeAPI") differs from base ("claude"). A value stored
    # under the raw id must win over one stored under the normalized base id.
    by_model = {"claudeAPI:claude-opus-5": "xhigh", "claude:claude-opus-5": "low"}
    assert resolve_reasoning_effort("claudeAPI", "claude-opus-5", by_model, "high") == "xhigh"


def test_resolve_falls_back_to_base_provider_key():
    # Legacy/alternate id normalization: claudeAPI -> claude. When only the base
    # key is stored, it is used.
    by_model = {"claude:claude-opus-5": "max"}
    assert resolve_reasoning_effort("claudeAPI", "claude-opus-5", by_model, "high") == "max"


def test_resolve_falls_back_to_legacy_global_value_when_no_per_model_entry():
    assert resolve_reasoning_effort("deepseek", "deepseek-v4-flash", {}, "high") == "high"


def test_resolve_invalid_stored_value_falls_to_model_default_not_remap():
    by_model = {"deepseek:deepseek-v4-flash": "medium"}
    assert resolve_reasoning_effort("deepseek", "deepseek-v4-flash", by_model, "max") == "high"


def test_resolve_does_not_apply_legacy_remap_to_valid_per_model_value():
    by_model = {"deepseek:deepseek-v4-flash": "low"}
    assert resolve_reasoning_effort("deepseek", "deepseek-v4-flash", by_model, "max") == "low"


def test_resolve_unsupported_provider_returns_none():
    assert resolve_reasoning_effort("gemini", "gemini-3.5-flash", {}, "high") is None


def test_resolve_non_dict_by_model_degrades_to_legacy():
    # A malformed persisted map (string/list from a hand-edited config) must not
    # crash the resolver; it degrades to the legacy global value.
    assert resolve_reasoning_effort("deepseek", "deepseek-v4-flash", "garbage", "high") == "high"
    assert resolve_reasoning_effort("deepseek", "deepseek-v4-flash", ["bad"], "high") == "high"
    assert resolve_reasoning_effort("deepseek", "deepseek-v4-flash", None, "high") == "high"


# --- R7 invariant: normalization always outputs a valid native enum ---
# Every supported provider/model, for every legacy global value that has ever
# appeared across vendors, must normalize to a value *inside that model's own
# allowed set*. This guards the remap table against silently emitting an enum
# the upstream API rejects, or bumping to a tier outside the model's enum.
# It only tests the current capability branches — it does not restructure the
# capability data.


def test_normalization_always_outputs_valid_native_enum():
    # One representative model per capability branch in get_reasoning_capability.
    supported_pairs = [
        ("deepseek", "deepseek-v4-flash"),
        ("zhipu", "glm-5.2"),
        ("claude", "claude-fable-5"),
        ("claude", "claude-opus-4-6"),  # max-only Claude variant
    ]
    # Union of every legacy effort value seen anywhere (native enums + the
    # legacy remap inputs minimal/none).
    legacy_inputs = ["low", "medium", "high", "xhigh", "max", "minimal", "none"]

    for provider, model in supported_pairs:
        cap = get_reasoning_capability(provider, model)
        assert cap["supported"], f"{provider}:{model} expected supported"
        allowed = [item["value"] for item in cap["options"]]
        for value in legacy_inputs:
            result = normalize_reasoning_effort(provider, model, value)
            assert result is not None, f"{provider}:{model} legacy={value!r} -> None"
            assert result in allowed, (
                f"{provider}:{model} legacy={value!r} -> {result!r} "
                f"not in allowed {allowed}"
            )
