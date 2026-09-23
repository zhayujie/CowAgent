# encoding:utf-8

"""Global language resolution — English-only.

This module is the single source of truth for the runtime UI language used
across the CLI, startup logs, error messages, agent prompts and channel
replies. It must NOT import project config (to avoid circular imports) and
must stay dependency-free so it can run at the earliest startup phase.

The application previously supported Simplified Chinese, Traditional Chinese
and English; language support has been removed. The whole runtime now runs in
English unconditionally:

  - ``resolve_language`` / ``detect_language`` / ``set_language`` always
    resolve to "en", whatever ``cow_lang`` or the environment says, so stale
    config values (e.g. ``"cow_lang": "zh"`` in an existing config.json)
    cannot re-enable Chinese.
  - ``t(zh_text, en_text)`` keeps its two-argument signature for call-site
    compatibility but always returns ``en_text``.
  - ``is_zh()`` always returns False.
"""

EN = "en"
SUPPORTED = (EN,)
DEFAULT_LANG = EN

# Resolved language cache; None until first resolution.
_resolved_lang = None


def _normalize(raw):
    """Map an arbitrary locale-ish string to a supported code, or None.

    Only English is supported; "auto" (and empty values) yield None so callers
    fall through to detection — which itself always answers English.
    """
    if not raw:
        return None
    value = str(raw).strip().lower().replace("_", "-")
    if value in ("auto", ""):
        return None
    return EN


def detect_language():
    """Auto-detection is retired; the runtime language is always English."""
    return DEFAULT_LANG


def resolve_language(configured=None):
    """Resolve the effective language from a configured value.

    `configured` is the raw `cow_lang` value from config.json (may be None,
    "auto", "zh" or "en"). Every value resolves to English; the result is
    cached globally.
    """
    global _resolved_lang
    _resolved_lang = _normalize(configured) or DEFAULT_LANG
    return _resolved_lang


def set_language(lang):
    """Force the resolved language (used by tests or per-request overrides)."""
    global _resolved_lang
    _resolved_lang = _normalize(lang) or DEFAULT_LANG
    return _resolved_lang


def get_language():
    """Return the currently resolved language, detecting lazily if needed."""
    global _resolved_lang
    if _resolved_lang is None:
        _resolved_lang = detect_language()
    return _resolved_lang


def is_zh():
    """Always False — Chinese UI strings are no longer produced."""
    return False


def t(zh_text, en_text):
    """Pick a string by the current language. Tiny inline-translation helper.

    Intended for one-off strings where a full message catalog is overkill:
        t("已中止", "Cancelled")
    The `zh_text` argument is kept for call-site compatibility with the old
    bilingual catalog; the English-only build always returns `en_text`.
    """
    return en_text
