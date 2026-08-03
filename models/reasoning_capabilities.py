"""Provider-native reasoning capability metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional


DEEPSEEK_VALUES = ["low", "high", "xhigh", "max"]
ZHIPU_VALUES = ["low", "medium", "high", "xhigh", "max"]
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
    "qwen3.8-max-preview",
)
DASHSCOPE_HIGH_MAX_MODELS = (
    "glm-5.2",
    "glm-5.1",
    "glm-5",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
)
DASHSCOPE_MAX_ONLY_MODELS = (
    "kimi/kimi-k3",
)


def _option(value: str) -> dict:
    return {"value": value, "label": value}


def _capability(
    values: list[str],
    default: str = "high",
    param: str = "reasoning_effort",
    thinking_only: bool = False,
) -> dict:
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
        return _capability(ZHIPU_VALUES, default="high")

    if base_pid == "claude":
        if model.startswith(CLAUDE_XHIGH_MODELS):
            return _capability(CLAUDE_VALUES, default="high", param="effort")
        if model.startswith(CLAUDE_MAX_ONLY_MODELS):
            return _capability(CLAUDE_MAX_ONLY_VALUES, default="high", param="effort")

    if base_pid == "dashscope":
        if model.startswith(DASHSCOPE_QWEN38_MODELS):
            return _capability(DASHSCOPE_QWEN38_VALUES, default="xhigh", thinking_only=True)
        if model.startswith(DASHSCOPE_HIGH_MAX_MODELS):
            return _capability(DASHSCOPE_HIGH_MAX_VALUES, default="high")
        if model.startswith(DASHSCOPE_MAX_ONLY_MODELS):
            return _capability(DASHSCOPE_MAX_ONLY_VALUES, default="max")

    if base_pid == "moonshot" and model.startswith("kimi-k3"):
        return _capability(KIMI_K3_VALUES, default="max", thinking_only=True)

    return {"supported": False, "options": []}


def normalize_reasoning_effort(provider_id: str, model_name: str, value: object) -> Optional[str]:
    """Validate a saved effort value against the active provider capability."""
    capability = get_reasoning_capability(provider_id, model_name)
    if not capability.get("supported"):
        return None

    base_pid = _base_provider_id(provider_id)
    model = (model_name or "").strip().lower()
    effort = str(value or "").strip()
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

    allowed = [item["value"] for item in capability.get("options", [])]
    if effort in allowed:
        return effort
    return capability.get("default")


def provider_reasoning_metadata(provider_id: str, model_name: str = "") -> dict:
    """Return a defensive copy safe to embed in JSON responses."""
    return deepcopy(get_reasoning_capability(provider_id, model_name))
