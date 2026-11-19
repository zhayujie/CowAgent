"""Credentials of the built-in ``cowagent`` provider.

The CowAgent model API is OpenAI-compatible (chat, images, audio, embeddings)
plus a web search endpoint, so every capability reuses the generic
OpenAI-compatible code paths with this one key and base.
"""

import os

from common import const, i18n
from config import conf


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def default_cowagent_api_base() -> str:
    """The site an unset base points at: the China site for a Chinese UI, otherwise the global one."""
    return const.COWAGENT_API_BASE_CN if i18n.get_language() == i18n.ZH else const.COWAGENT_API_BASE_GLOBAL


def resolve_cowagent_credentials():
    """Return ``(api_key, api_base)``: config first, then environment, then
    the site matching the UI language."""
    api_key = _text(conf().get("cowagent_api_key")) or _text(os.environ.get("COWAGENT_API_KEY"))
    api_base = (
        _text(conf().get("cowagent_api_base"))
        or _text(os.environ.get("COWAGENT_API_BASE"))
        or default_cowagent_api_base()
    )
    return api_key, api_base.rstrip("/")
