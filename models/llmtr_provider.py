"""Credentials of the built-in ``llmtr`` provider.

LLMTR is an OpenAI-compatible chat gateway. The generic Chat Completions
path is reused with this key and base.
"""

import os

from common import const
from config import conf


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def default_llmtr_api_base() -> str:
    return const.LLMTR_API_BASE


def resolve_llmtr_credentials():
    """Return ``(api_key, api_base)``: config first, then environment, then
    the public LLMTR endpoint."""
    api_key = _text(conf().get("llmtr_api_key")) or _text(os.environ.get("LLMTR_API_KEY"))
    api_base = (
        _text(conf().get("llmtr_api_base"))
        or _text(os.environ.get("LLMTR_API_BASE"))
        or default_llmtr_api_base()
    )
    return api_key, api_base.rstrip("/")
