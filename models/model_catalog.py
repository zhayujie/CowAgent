# encoding:utf-8

"""
Per-provider model catalog: user-managed model entries with metadata
(capability tags, context window, max output tokens).

Config model (config.json top-level key ``provider_model_catalog``)::

    "provider_model_catalog": {
        "zhipu": [                          # built-in vendor id
            {"name": "glm-5.3-flash", "capabilities": ["chat"],
             "context_window": 1000000, "max_output_tokens": 65536}
        ],
        "custom:3f2a9c1b": [ ... ]          # user-defined provider
    }

Semantics
---------
- When a provider has a catalog, it REPLACES the provider's preset model
  list wherever models are offered; the session picker filters to entries
  tagged "chat". Without a catalog the preset behaviour is unchanged.
- Saving an empty list removes the provider's catalog (back to presets).
"""

import json
import os

from config import conf, get_data_root, read_config_template
from common.log import logger

CATALOG_KEY = "provider_model_catalog"

VALID_CAPABILITIES = ("chat", "vision", "video", "image", "embedding", "asr", "tts")
DEFAULT_CAPABILITIES = ["chat"]


def _config_path() -> str:
    return os.path.join(get_data_root(), "config.json")


def _read_file_config() -> dict:
    """Baseline dict for a partial write to config.json (same contract as
    web_channel's helper: seed from the template on a fresh install)."""
    path = _config_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return read_config_template()


def normalize_entry(raw) -> dict:
    """Validate one catalog entry, filling defaults. Raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("model entry must be an object")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("model name is required")

    caps = raw.get("capabilities")
    if caps in (None, ""):
        caps = list(DEFAULT_CAPABILITIES)
    if isinstance(caps, str):
        caps = [caps]
    if not isinstance(caps, list):
        raise ValueError(f"capabilities for {name} must be a list")
    caps = [str(c).strip().lower() for c in caps if str(c).strip()]
    unknown = [c for c in caps if c not in VALID_CAPABILITIES]
    if unknown:
        raise ValueError(f"unknown capability for {name}: {unknown[0]}")
    if not caps:
        caps = list(DEFAULT_CAPABILITIES)

    entry = {"name": name, "capabilities": caps}
    for key in ("context_window", "max_output_tokens"):
        value = raw.get(key)
        if value in (None, ""):
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} for {name} must be a positive integer")
        if value <= 0:
            raise ValueError(f"{key} for {name} must be a positive integer")
        entry[key] = value
    return entry


def get_catalog_map() -> dict:
    """Live catalog map (provider id -> entries), from the in-memory config.

    Writers keep conf() and config.json in sync, so reads never hit disk —
    the budget and request paths call this every LLM turn."""
    catalog = conf().get(CATALOG_KEY)
    return catalog if isinstance(catalog, dict) else {}


def get_catalog(provider_id) -> list:
    """Return the catalog entries for one provider (empty when absent)."""
    if not provider_id:
        return []
    entries = get_catalog_map().get(provider_id)
    return entries if isinstance(entries, list) else []


def save_catalog(provider_id, models) -> list:
    """Replace one provider's catalog wholesale; an empty list removes it."""
    if not provider_id:
        raise ValueError("provider id is required")
    if not isinstance(models, list):
        raise ValueError("models must be a list")
    entries = [normalize_entry(m) for m in models]
    names = [e["name"] for e in entries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate model name in catalog")

    data = _read_file_config()
    catalog = data.get(CATALOG_KEY)
    if not isinstance(catalog, dict):
        catalog = {}
    if entries:
        catalog[provider_id] = entries
    else:
        catalog.pop(provider_id, None)
    if catalog:
        data[CATALOG_KEY] = catalog
    else:
        data.pop(CATALOG_KEY, None)
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    # Keep the in-memory config in sync (same contract as the web config
    # handlers) so runtime readers see the change without a restart.
    local = conf()
    catalog = local.get(CATALOG_KEY)
    if not isinstance(catalog, dict):
        catalog = {}
    if entries:
        catalog[provider_id] = entries
    else:
        catalog.pop(provider_id, None)
    if catalog:
        local[CATALOG_KEY] = catalog
    else:
        local.pop(CATALOG_KEY, None)

    logger.info(f"[ModelCatalog] provider {provider_id} saved: {len(entries)} models")
    return entries


def remove_catalog(provider_id) -> None:
    """Drop one provider's catalog if present (used on provider delete)."""
    try:
        save_catalog(provider_id, [])
    except (OSError, ValueError) as e:
        logger.warning(f"[ModelCatalog] failed to remove catalog for {provider_id}: {e}")


def resolve_model_meta(provider_id, model_name) -> dict:
    """Catalog metadata for one model, or {} when not catalogued."""
    name = str(model_name or "").strip()
    if not provider_id or not name:
        return {}
    for entry in get_catalog(provider_id):
        if entry.get("name") == name:
            return entry
    return {}
