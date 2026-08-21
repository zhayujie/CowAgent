"""Provider-native reasoning capability metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional


DEEPSEEK_VALUES = ["low", "high", "xhigh", "max"]
ZHIPU_VALUES = ["low", "medium", "high", "xhigh", "max"]
# GLM-5.3 always thinks (rejects thinking.type="disabled") and only exposes
# three effort tiers. See https://docs.bigmodel.cn GLM-5.3 release notes.
ZHIPU_GLM53_VALUES = ["low", "high", "max"]
CLAUDE_VALUES = ["low", "medium", "high", "xhigh", "max"]
CLAUDE_MAX_ONLY_VALUES = ["low", "medium", "high", "max"]
DASHSCOPE_QWEN38_VALUES = ["low", "medium", "xhigh"]
DASHSCOPE_HIGH_MAX_VALUES = ["high", "max"]
DASHSCOPE_MAX_ONLY_VALUES = ["max"]
KIMI_K3_VALUES = ["low", "high", "max"]
CLAUDE_XHIGH_MODELS = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
)
CLAUDE_MAX_ONLY_MODELS = (
    "claude-mythos-preview",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-4-5",
)
DASHSCOPE_QWEN38_MODELS = (
    # qwen3.8-max and its -preview snapshot share the low/medium/xhigh enum
    # (default xhigh) and always think.
    "qwen3.8-max",
)
DASHSCOPE_HIGH_MAX_MODELS = (
    "glm-5.2",
    "glm-5.1",
    "glm-5",
)
DASHSCOPE_MAX_ONLY_MODELS = (
    "kimi/kimi-k3",
)
# GLM-5.3 is always-thinking regardless of which gateway proxies it.
ZHIPU_GLM53_MODELS = (
    "glm-5.3",
)


def _option(value: str) -> dict:
    return {"value": value, "label": value}


def _capability(
    values: list[str],
    default: str = "high",
    param: str = "reasoning_effort",
    thinking_only: bool = False,
) -> dict:
    """Build the JSON shape shared by Web/Desktop config clients."""
    capability = {
        "supported": True,
        "param": param,
        "default": default,
        "options": [_option(value) for value in values],
    }
    if thinking_only:
        capability["thinking_only"] = True
    return capability


def _base_provider_id(provider_id: str) -> str:
    """Normalize legacy config ids to the provider ids used in this module."""
    pid = (provider_id or "").strip()
    if pid.startswith("custom:"):
        return "custom"
    if pid == "chatGPT":
        return "openai"
    if pid == "claudeAPI":
        return "claude"
    return pid


def get_reasoning_capability(provider_id: str, model_name: str = "") -> dict:
    """Return provider-native reasoning metadata for a provider/model pair."""
    base_pid = _base_provider_id(provider_id)
    model = (model_name or "").strip().lower()

    if base_pid == "deepseek" and model.startswith("deepseek-v4"):
        return _capability(DEEPSEEK_VALUES, default="high")

    if base_pid == "zhipu":
        if model.startswith(ZHIPU_GLM53_MODELS):
            return _capability(ZHIPU_GLM53_VALUES, default="max", thinking_only=True)
        return _capability(ZHIPU_VALUES, default="high")

    if base_pid == "claude":
        # Claude uses Anthropic's output_config.effort field, so the UI may
        # expose it even when the generic thinking toggle is disabled.
        if model.startswith(CLAUDE_XHIGH_MODELS):
            return _capability(CLAUDE_VALUES, default="high", param="effort")
        if model.startswith(CLAUDE_MAX_ONLY_MODELS):
            return _capability(CLAUDE_MAX_ONLY_VALUES, default="high", param="effort")

    if base_pid == "dashscope":
        # DashScope proxies several vendors. Keep capabilities model-scoped so
        # unsupported Qwen/GLM/Kimi variants do not inherit another enum set.
        if model.startswith(DASHSCOPE_QWEN38_MODELS):
            return _capability(DASHSCOPE_QWEN38_VALUES, default="xhigh", thinking_only=True)
        # deepseek-v4 takes the same enum wherever it is hosted; the two
        # variants only differ in how they map the values internally.
        if model.startswith("deepseek-v4"):
            return _capability(DEEPSEEK_VALUES, default="high")
        if model.startswith(ZHIPU_GLM53_MODELS):
            return _capability(ZHIPU_GLM53_VALUES, default="max", thinking_only=True)
        if model.startswith(DASHSCOPE_HIGH_MAX_MODELS):
            return _capability(DASHSCOPE_HIGH_MAX_VALUES, default="high")
        if model.startswith(DASHSCOPE_MAX_ONLY_MODELS):
            return _capability(DASHSCOPE_MAX_ONLY_VALUES, default="max")

    if base_pid == "moonshot" and model.startswith("kimi-k3"):
        return _capability(KIMI_K3_VALUES, default="max", thinking_only=True)

    if base_pid == "linkai":
        # LinkAI is a gateway; only expose passthrough effort for models whose
        # upstream protocol has been verified here.
        if model.startswith("deepseek-v4"):
            return _capability(DEEPSEEK_VALUES, default="high")
        if model.startswith(ZHIPU_GLM53_MODELS):
            return _capability(ZHIPU_GLM53_VALUES, default="max", thinking_only=True)
        if model.startswith("glm-"):
            return _capability(ZHIPU_VALUES, default="high")
        if model.startswith("kimi-k3"):
            return _capability(KIMI_K3_VALUES, default="max", thinking_only=True)

    return {"supported": False, "options": []}


def _legacy_remap(base_pid: str, model: str, effort: str) -> str:
    """Map a legacy global effort value to a provider-native enum.

    This exists only to migrate the old single global ``reasoning_effort`` key.
    Per-model values stored in ``reasoning_effort_by_model`` are *not* remapped
    (see ``resolve_reasoning_effort``) — they are the model's own intent.
    """
    if base_pid == "dashscope":
        if model.startswith(DASHSCOPE_QWEN38_MODELS):
            effort = {
                "high": "xhigh",
                "max": "xhigh",
                "minimal": "low",
            }.get(effort, effort)
        elif model.startswith(DASHSCOPE_HIGH_MAX_MODELS):
            effort = {
                "low": "high",
                "medium": "high",
                "xhigh": "max",
            }.get(effort, effort)
        elif model.startswith(DASHSCOPE_MAX_ONLY_MODELS):
            effort = {
                "low": "max",
                "medium": "max",
                "high": "max",
                "xhigh": "max",
            }.get(effort, effort)
    elif base_pid == "linkai":
        if model.startswith("glm-"):
            effort = {
                "minimal": "high",
                "none": "high",
            }.get(effort, effort)
        elif model.startswith("kimi-k3"):
            effort = {
                "medium": "max",
                "xhigh": "max",
            }.get(effort, effort)

    return effort


def _validate_effort(value: object, capability: dict) -> Optional[str]:
    """Pure validation: return ``value`` if it is in the capability's allowed
    set, otherwise fall back to the capability's default. No remapping."""
    effort = str(value or "").strip()
    allowed = [item["value"] for item in capability.get("options", [])]
    if effort in allowed:
        return effort
    return capability.get("default")


def normalize_reasoning_effort(provider_id: str, model_name: str, value: object) -> Optional[str]:
    """Validate a saved effort value against the active provider capability.

    Applies the legacy remap (migration of the old global key). See
    ``resolve_reasoning_effort`` for the per-model config resolution path.
    """
    capability = get_reasoning_capability(provider_id, model_name)
    if not capability.get("supported"):
        return None

    base_pid = _base_provider_id(provider_id)
    model = (model_name or "").strip().lower()
    effort = _legacy_remap(base_pid, model, str(value or "").strip())
    return _validate_effort(effort, capability)


def resolve_reasoning_effort(
    provider_id: str, model_name: str, by_model: dict, legacy_value: object
) -> Optional[str]:
    """Resolve the effective effort for an active provider/model.

    This is *config resolution*, not provider normalization: it reads a
    per-model value from ``reasoning_effort_by_model`` and only validates it
    against the model's capability. It never remaps across vendors — a value a
    user set for a specific model is their intent for that model.

    Candidate keys are tried in order so that ``custom:foo:model`` is not
    collapsed to ``custom:model`` when two custom providers share a model name:
      ``<raw_provider>:<model>`` → ``<base_provider>:<model>`` → ``<model>``

    When no per-model value exists, falls back to the legacy global
    ``reasoning_effort`` (which may be remapped for migration).
    """
    raw = (provider_id or "").strip()
    base = _base_provider_id(raw)
    model = (model_name or "").strip().lower()
    capability = get_reasoning_capability(base, model)
    if not capability.get("supported"):
        return None

    # Guard against a malformed persisted value (e.g. a hand-edited config.json
    # or env override that turned the map into a non-dict) so we degrade to the
    # legacy fallback instead of raising/returning a weird value.
    if not isinstance(by_model, dict):
        by_model = {}

    for key in (f"{raw}:{model}", f"{base}:{model}", model):
        if key in by_model:
            return _validate_effort(by_model[key], capability)

    return normalize_reasoning_effort(base, model, legacy_value)


def provider_reasoning_metadata(provider_id: str, model_name: str = "") -> dict:
    """Return a defensive copy safe to embed in JSON responses."""
    return deepcopy(get_reasoning_capability(provider_id, model_name))
