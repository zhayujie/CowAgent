# encoding:utf-8

"""
Centralized resolver for custom (OpenAI-compatible) provider credentials.

CowAgent historically supported only a *single* custom provider via the flat
config keys ``custom_api_key`` / ``custom_api_base``. This module adds support
for *multiple* custom providers (see issue #2838) while remaining 100%
backward compatible.

Config model
------------
- ``custom_providers``: list of dicts, each describing one custom provider::

      {
          "name": "siliconflow",          # unique, user-facing identifier
          "api_key": "sk-...",            # required
          "api_base": "https://...",     # required, must be OpenAI-compatible
          "model": "deepseek-ai/DeepSeek-V3"  # optional default model
      }

- ``custom_active_provider``: the ``name`` of the provider to use. When empty
  (or pointing to a non-existent name) we fall back to the first provider in
  the list, and finally to the legacy ``custom_api_key`` / ``custom_api_base``.

Backward-compatibility contract
-------------------------------
When ``custom_providers`` is empty, ``resolve_custom_credentials`` returns
exactly the legacy ``custom_api_key`` / ``custom_api_base`` values, so existing
deployments behave byte-for-byte identically.
"""

from config import conf
from common.log import logger


def get_custom_providers():
    """Return the list of configured custom providers (always a list)."""
    providers = conf().get("custom_providers")
    if not isinstance(providers, list):
        return []
    # Keep only well-formed entries with a name.
    return [p for p in providers if isinstance(p, dict) and p.get("name")]


def _find_active_provider(providers):
    """Pick the active provider from the list, or None when list is empty."""
    if not providers:
        return None
    active_name = conf().get("custom_active_provider") or ""
    if active_name:
        for p in providers:
            if p.get("name") == active_name:
                return p
        logger.warning(
            "[CUSTOM] active provider '%s' not found in custom_providers, "
            "falling back to the first entry", active_name
        )
    return providers[0]


def resolve_custom_credentials():
    """Resolve the effective (api_key, api_base, model) for custom mode.

    Resolution order:
      1. The active entry in ``custom_providers`` (multi-provider mode).
      2. The legacy flat keys ``custom_api_key`` / ``custom_api_base``.

    :return: tuple ``(api_key, api_base, model)``. ``api_base`` and ``model``
             may be ``None`` / empty when not configured.
    """
    provider = _find_active_provider(get_custom_providers())
    if provider is not None:
        return (
            provider.get("api_key", ""),
            provider.get("api_base") or None,
            provider.get("model") or None,
        )
    # Legacy single-provider fallback — unchanged behavior.
    return (
        conf().get("custom_api_key", ""),
        conf().get("custom_api_base") or None,
        None,
    )
