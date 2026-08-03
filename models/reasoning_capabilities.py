"""Provider-native reasoning capability metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional


DEEPSEEK_VALUES = ["low", "high", "xhigh", "max"]
ZHIPU_VALUES = ["low", "medium", "high", "xhigh", "max"]


def _option(value: str) -> dict:
    return {"value": value, "label": value}


def _capability(values: list[str], default: str = "high", param: str = "reasoning_effort") -> dict:
    return {
        "supported": True,
        "param": param,
        "default": default,
        "options": [_option(value) for value in values],
    }


def _base_provider_id(provider_id: str) -> str:
    pid = (provider_id or "").strip()
    if pid.startswith("custom:"):
        return "custom"
    if pid == "chatGPT":
        return "openai"
    return pid


def get_reasoning_capability(provider_id: str, model_name: str = "") -> dict:
    """Return provider-native reasoning metadata for a provider/model pair."""
    base_pid = _base_provider_id(provider_id)
    model = (model_name or "").strip().lower()

    if base_pid == "deepseek" and model.startswith("deepseek-v4"):
        return _capability(DEEPSEEK_VALUES, default="high")

    if base_pid == "zhipu":
        return _capability(ZHIPU_VALUES, default="high")

    return {"supported": False, "options": []}


def normalize_reasoning_effort(provider_id: str, model_name: str, value: object) -> Optional[str]:
    """Validate a saved effort value against the active provider capability."""
    capability = get_reasoning_capability(provider_id, model_name)
    if not capability.get("supported"):
        return None

    allowed = [item["value"] for item in capability.get("options", [])]
    effort = str(value or "").strip()
    if effort in allowed:
        return effort
    return capability.get("default")


def provider_reasoning_metadata(provider_id: str, model_name: str = "") -> dict:
    """Return a defensive copy safe to embed in JSON responses."""
    return deepcopy(get_reasoning_capability(provider_id, model_name))
