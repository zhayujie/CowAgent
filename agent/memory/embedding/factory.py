"""
Shared embedding provider factory.

Resolves the embedding provider purely from config.json, so every caller
(agent initialization, knowledge base sync, index rebuild, ...) selects the
same provider instead of silently degrading to keyword-only search.

Two paths:
  A. Default (no `embedding_provider` in config.json):
     Auto-init OpenAI -> LinkAI fallback.
  B. Explicit (`embedding_provider` is set):
     Initialize the requested vendor with unified dim (default per vendor).
"""

import os
from typing import Optional

from common.log import logger

# Track whether the embedding model log has been printed in this process,
# so we avoid spamming it once per session/caller.
_embedding_logged: bool = False


def create_default_embedding_provider():
    """Build the embedding provider from config, or None for keyword-only mode."""
    from config import conf

    explicit_provider = (conf().get("embedding_provider") or "").strip().lower()
    if not explicit_provider:
        return _init_legacy_provider()
    return _init_explicit_provider(explicit_provider)


def _init_legacy_provider():
    """Legacy auto-init path: OpenAI -> LinkAI."""
    from agent.memory.embedding.provider import create_embedding_provider
    from config import conf

    embedding_provider = None
    embedding_model = None

    openai_api_key = conf().get("open_ai_api_key", "")
    openai_api_base = conf().get("open_ai_api_base", "")
    if openai_api_key and openai_api_key not in ["", "YOUR API KEY", "YOUR_API_KEY"]:
        try:
            model = "text-embedding-3-small"
            embedding_provider = create_embedding_provider(
                provider="openai",
                model=model,
                api_key=openai_api_key,
                api_base=openai_api_base or "https://api.openai.com/v1",
            )
            embedding_model = f"openai/{model}"
        except Exception as e:
            logger.warning(f"[EmbeddingFactory] OpenAI embedding failed: {e}")

    if embedding_provider is None:
        linkai_api_key = conf().get("linkai_api_key", "") or os.environ.get("LINKAI_API_KEY", "")
        linkai_api_base = conf().get("linkai_api_base", "https://api.link-ai.tech")
        if linkai_api_key and linkai_api_key not in ["", "YOUR API KEY", "YOUR_API_KEY"]:
            try:
                model = "text-embedding-3-small"
                embedding_provider = create_embedding_provider(
                    provider="linkai",
                    model=model,
                    api_key=linkai_api_key,
                    api_base=f"{linkai_api_base}/v1",
                    source_tagged=True,
                )
                embedding_model = f"linkai/{model}"
            except Exception as e:
                logger.warning(f"[EmbeddingFactory] LinkAI embedding failed: {e}")

    if embedding_provider is not None and embedding_model:
        _log_provider_once(f"{embedding_model} (dim={embedding_provider.dimensions})")

    return embedding_provider


def _init_explicit_provider(provider_key: str):
    """Explicit-provider path: build the configured vendor."""
    from agent.memory.embedding.provider import EMBEDDING_VENDORS, create_embedding_provider
    from config import conf

    # Custom providers ("custom:<id>") resolve credentials from custom_providers.
    resolved_provider_key = provider_key
    if provider_key.startswith("custom:"):
        resolved_provider_key = "custom"

    meta = EMBEDDING_VENDORS.get(resolved_provider_key)
    if meta is None:
        logger.error(
            f"[EmbeddingFactory] Unknown embedding_provider '{provider_key}'. "
            f"Supported: {sorted(EMBEDDING_VENDORS.keys())}. "
            f"Memory will run in keyword-only mode."
        )
        return None

    api_key = _resolve_api_key(provider_key)
    api_base = _resolve_api_base(provider_key, meta["default_base_url"])

    if not api_key:
        logger.error(
            f"[EmbeddingFactory] embedding_provider='{provider_key}' is set but its "
            f"API key is missing. Memory will run in keyword-only mode."
        )
        return None

    model = (conf().get("embedding_model") or "").strip()
    # Custom providers without a model fall back to the provider's default.
    if not model and resolved_provider_key == "custom":
        from models.custom_provider import parse_custom_bot_type, get_custom_providers, _find_provider_by_id
        _, custom_id = parse_custom_bot_type(provider_key)
        if custom_id:
            entry = _find_provider_by_id(get_custom_providers(), custom_id)
            if entry and entry.get("model"):
                model = entry["model"]
    if not model and resolved_provider_key != "custom":
        model = meta["default_model"]

    try:
        cfg_dim = int(conf().get("embedding_dimensions") or 0)
    except (TypeError, ValueError):
        cfg_dim = 0
    dim = cfg_dim if cfg_dim > 0 else meta["default_dimensions"]

    try:
        provider = create_embedding_provider(
            provider=resolved_provider_key,
            model=model,
            api_key=api_key,
            api_base=api_base,
            dimensions=dim,
            source_tagged=True if resolved_provider_key == "linkai" else None,
        )
    except Exception as e:
        logger.error(
            f"[EmbeddingFactory] Failed to init embedding provider "
            f"'{provider_key}/{model}': {e}"
        )
        return None

    _log_provider_once(f"{provider_key}/{model} (dim={provider.dimensions})")
    return provider


def _resolve_api_key(provider_key: str) -> str:
    """Pick the API key for an explicit embedding provider from config."""
    from config import conf

    if provider_key.startswith("custom:"):
        from models.custom_provider import parse_custom_bot_type, get_custom_providers, _find_provider_by_id
        _, custom_id = parse_custom_bot_type(provider_key)
        if custom_id:
            entry = _find_provider_by_id(get_custom_providers(), custom_id)
            if entry:
                return entry.get("api_key", "")
        return ""

    key_map = {
        "openai":    "open_ai_api_key",
        "linkai":    "linkai_api_key",
        "dashscope": "dashscope_api_key",
        "doubao":    "ark_api_key",
        "zhipu":     "zhipu_ai_api_key",
    }
    field = key_map.get(provider_key)
    if not field:
        return ""
    value = conf().get(field, "") or ""
    if value in ["", "YOUR API KEY", "YOUR_API_KEY"]:
        return ""
    return value


def _resolve_api_base(provider_key: str, default_base: str) -> str:
    """Pick the API base for an explicit embedding provider from config."""
    from config import conf

    if provider_key.startswith("custom:"):
        from models.custom_provider import parse_custom_bot_type, get_custom_providers, _find_provider_by_id
        _, custom_id = parse_custom_bot_type(provider_key)
        if custom_id:
            entry = _find_provider_by_id(get_custom_providers(), custom_id)
            if entry and entry.get("api_base"):
                return entry["api_base"]
        return default_base

    base_map = {
        "openai":    "open_ai_api_base",
        "linkai":    "linkai_api_base",
        "doubao":    "ark_base_url",
        "zhipu":     "zhipu_ai_api_base",
    }
    field = base_map.get(provider_key)
    if not field:
        return default_base
    value = (conf().get(field) or "").strip()
    if not value:
        return default_base
    if provider_key == "linkai" and not value.rstrip("/").endswith("/v1"):
        return f"{value.rstrip('/')}/v1"
    return value


def _log_provider_once(detail: str):
    global _embedding_logged
    if not _embedding_logged:
        logger.info(f"[EmbeddingFactory] Embedding model in use: {detail}")
        _embedding_logged = True
