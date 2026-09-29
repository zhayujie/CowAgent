# encoding:utf-8

"""Per-provider model catalog: user overrides layered on the built-in presets.

The catalog is an OVERLAY, not a replacement. A provider's built-in preset
models remain the base list; the catalog only records what the user actually
changed on top of them:

- ``overrides``: entries the user edited or added. An override matched by name
  to a preset replaces that preset's metadata; an override with a new name is
  an added model.
- ``hidden``: preset model names the user removed (tombstones), so a deleted
  preset is not silently restored on the next read.

Anything the user did not touch is never persisted, so preset metadata (context
window, max output, capabilities) keeps following the code-side constants and a
later constant bump reaches every user who never overrode that model.

Storage (``get_data_root()/system/models.json``)::

    {
        "providers": {
            "zhipu": {
                "overrides": [
                    {"name": "glm-5.3", "capabilities": ["text"],
                     "context_window": 2000000}
                ],
                "hidden": ["glm-4.7"]
            },
            "custom:3f2a9c1b": {"overrides": [ ... ], "hidden": []}
        }
    }

A custom (OpenAI-compatible) provider has no presets, so its ``overrides`` are
simply its whole model list and ``hidden`` stays empty.
"""

import json
import os

from common.log import logger

# Legacy: catalogs used to live under this key in config.json (pre-overlay),
# where each provider stored a full replacement list. On the first read after
# the upgrade we migrate any such entries into the overlay store (as overrides)
# and strip the key from config.json, so an early adopter keeps their models.
LEGACY_CATALOG_KEY = "provider_model_catalog"

# Capability tags route a model into the matching tool position. "text" marks
# a conversational model: only text-tagged entries appear in the main-model
# (chat) dropdown and the conversation switcher. A model may hold several
# tags (e.g. text + vision for a VL model).
VALID_CAPABILITIES = ("text", "vision", "video", "image", "embedding", "asr", "tts")
DEFAULT_CAPABILITIES = ["text"]


def _store_path() -> str:
    """Path to the catalog overlay under the instance's shared workspace
    (``<workspace>/system/models.json``, e.g. ``~/cow/system/models.json``)."""
    from common import state_dir
    return str(state_dir.models_catalog_file())


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
    # Silently drop unrecognized tags (e.g. hand-edited config) instead of
    # rejecting the whole entry — the UI only ever offers valid ones.
    caps = [str(c).strip().lower() for c in caps if str(c).strip() in VALID_CAPABILITIES]
    # A model with no tags would be unreachable everywhere (not text, not any
    # capability), so an empty set falls back to the default: text.
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


def _normalize_provider_doc(raw) -> dict:
    """Coerce one provider's stored doc into {overrides: [...], hidden: [...]}.

    Accepts the legacy shape too — a bare list of entries is read as overrides
    with no tombstones — so an older config or a hand-edit still loads."""
    overrides = []
    hidden = []
    if isinstance(raw, list):
        entries = raw
        raw_hidden = []
    elif isinstance(raw, dict):
        entries = raw.get("overrides")
        raw_hidden = raw.get("hidden")
    else:
        return {"overrides": [], "hidden": []}

    for e in entries or []:
        try:
            overrides.append(normalize_entry(e))
        except (ValueError, TypeError, AttributeError):
            continue  # unparseable entry: skip rather than break reads
    seen = set()
    for name in raw_hidden or []:
        name = str(name or "").strip()
        if name and name not in seen:
            seen.add(name)
            hidden.append(name)
    return {"overrides": overrides, "hidden": hidden}


def _migrate_legacy_config() -> dict:
    """One-shot import of the pre-overlay ``provider_model_catalog`` (a full
    replacement list per provider) into the overlay store, then drop it from
    config.json. Returns the migrated store, or {} when there is nothing to do.

    The old lists become ``overrides`` with no tombstones — the closest overlay
    to the old "replace the preset list" behaviour — so an early adopter keeps
    exactly the models they had. Best effort: any failure just leaves the old
    key in place and yields {}."""
    try:
        from config import conf
        legacy = conf().get(LEGACY_CATALOG_KEY)
    except Exception:
        return {}
    if not isinstance(legacy, dict) or not legacy:
        return {}

    providers = {}
    for pid, entries in legacy.items():
        if not isinstance(entries, list):
            continue
        doc = _normalize_provider_doc(entries)
        if doc["overrides"]:
            providers[pid] = doc
    store = {"providers": providers}
    try:
        _write_store(store)
        _strip_legacy_config_key()
        logger.info(f"[ModelCatalog] migrated {len(providers)} legacy provider catalogs to overlay store")
    except OSError as e:
        logger.warning(f"[ModelCatalog] legacy migration failed: {e}")
        return {}
    return store


def _strip_legacy_config_key() -> None:
    """Remove ``provider_model_catalog`` from the in-memory config and its
    config.json file, so the migration runs only once."""
    try:
        from config import conf, get_data_root
    except Exception:
        return
    conf().pop(LEGACY_CATALOG_KEY, None)
    cfg_path = os.path.join(get_data_root(), "config.json")
    if not os.path.exists(cfg_path):
        return
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if LEGACY_CATALOG_KEY in data:
        data.pop(LEGACY_CATALOG_KEY, None)
        _write_json_atomic(cfg_path, data)


def _read_store() -> dict:
    """Load the overlay store, healing entries and absorbing legacy shapes.

    Never raises: a corrupt file yields an empty store rather than taking the
    whole models view down."""
    path = _store_path()
    raw = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError) as e:
            logger.warning(f"[ModelCatalog] failed to read {path}: {e}")
            raw = None
    else:
        # No overlay file yet: this may be a fresh install or an upgrade from a
        # build that stored catalogs in config.json. Migrate the latter once.
        migrated = _migrate_legacy_config()
        if migrated.get("providers"):
            return migrated

    providers = {}
    if isinstance(raw, dict):
        src = raw.get("providers")
        if isinstance(src, dict):
            for pid, doc in src.items():
                providers[pid] = _normalize_provider_doc(doc)
    return {"providers": providers}


def _write_json_atomic(path: str, data: dict) -> None:
    """Write ``data`` to ``path`` through a sibling file, then swap it in.

    Both files written from this module are read back with a bare json.load, and
    a partial one is worse than a missing one. Writing straight into the target
    truncates it before the new bytes exist, so anything that fails while
    serialising -- a full disk, an interrupted update -- leaves a document that
    no longer parses. For the overlay store that reads as "the user has no
    overrides at all" (``_read_store`` deliberately swallows the decode error so
    one bad file cannot take the whole models view down), and the next save
    writes that empty baseline back, which turns a recoverable file into a
    permanent loss. The config.json side is the file the console also writes: a
    truncated user config is what ``load_config`` treats as corruption.
    """
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
        raise


def _write_store(store: dict) -> None:
    path = _store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write_json_atomic(path, store)


# In-memory cache so the budget/request paths (called every LLM turn) don't hit
# disk. Invalidated on every write, which all goes through this module.
_cache = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = _read_store()
    return _cache


def _invalidate() -> None:
    global _cache
    _cache = None


def get_catalog_map() -> dict:
    """Override entries per provider (provider id -> [entries]).

    These are the user's overrides only, NOT the merged list — callers layer
    them onto the presets. Empty when a provider has no overrides."""
    out = {}
    for pid, doc in _load()["providers"].items():
        if doc["overrides"]:
            out[pid] = [dict(e) for e in doc["overrides"]]
    return out


def get_hidden_map() -> dict:
    """Removed preset names per provider (provider id -> [names]) — tombstones
    the merge step subtracts from the preset base list."""
    out = {}
    for pid, doc in _load()["providers"].items():
        if doc["hidden"]:
            out[pid] = list(doc["hidden"])
    return out


def get_catalog(provider_id) -> list:
    """Return the override entries for one provider (empty when absent)."""
    if not provider_id:
        return []
    doc = _load()["providers"].get(provider_id)
    return [dict(e) for e in doc["overrides"]] if doc else []


def get_hidden(provider_id) -> list:
    """Return the tombstoned preset names for one provider."""
    if not provider_id:
        return []
    doc = _load()["providers"].get(provider_id)
    return list(doc["hidden"]) if doc else []


def save_catalog(provider_id, models, hidden=None) -> list:
    """Replace one provider's overlay (overrides + hidden tombstones).

    An empty overrides list with no tombstones drops the provider entirely,
    which restores the pure preset behaviour."""
    if not provider_id:
        raise ValueError("provider id is required")
    if not isinstance(models, list):
        raise ValueError("models must be a list")
    entries = [normalize_entry(m) for m in models]
    names = [e["name"] for e in entries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate model name in catalog")

    tombstones = []
    seen = set()
    for name in hidden or []:
        name = str(name or "").strip()
        if name and name not in seen and name not in names:
            # A name that is both overridden and hidden makes no sense; the
            # override wins, so it is never tombstoned.
            seen.add(name)
            tombstones.append(name)

    store = _read_store()  # read fresh so a concurrent edit isn't clobbered
    providers = store["providers"]
    if entries or tombstones:
        providers[provider_id] = {"overrides": entries, "hidden": tombstones}
    else:
        providers.pop(provider_id, None)
    _write_store(store)
    _invalidate()

    logger.info(
        f"[ModelCatalog] provider {provider_id} saved: "
        f"{len(entries)} overrides, {len(tombstones)} hidden"
    )
    return entries


def remove_catalog(provider_id) -> None:
    """Drop one provider's overlay if present (used on provider delete)."""
    try:
        save_catalog(provider_id, [], [])
    except (OSError, ValueError) as e:
        logger.warning(f"[ModelCatalog] failed to remove catalog for {provider_id}: {e}")


def resolve_model_meta(provider_id, model_name) -> dict:
    """Catalog OVERRIDE metadata for one model, or {} when the user never
    overrode it.

    Returning {} for an untouched preset is deliberate: the budget resolver
    then falls back to the code-side constants, so a later constant change
    reaches users who never customized that model."""
    name = str(model_name or "").strip()
    if not provider_id or not name:
        return {}
    for entry in get_catalog(provider_id):
        if entry.get("name") == name:
            return entry
    return {}
