# encoding:utf-8

"""Lightweight global language detection and resolution.

This module is the single source of truth for the runtime UI language used
across the CLI, startup logs, error messages, agent prompts and channel
replies. It must NOT import project config (to avoid circular imports) and
must stay dependency-free so it can run at the earliest startup phase.

Resolution priority (highest first):
  1. Explicit `cow_lang` from config.json — also covers Docker/CI, since any
     config key is overridable via its uppercase env var (e.g. COW_LANG=zh),
     handled by config.load_config() before resolution. COW_LANG is a private
     name to avoid clashing with the gettext-standard LANGUAGE variable.
  2. macOS `defaults read -g AppleLocale` (system-level preference; a Chinese
     system locale is a strong signal that beats a shell-default LANG)
  3. Standard locale env vars: LC_ALL > LC_MESSAGES > LANG
  4. Python locale module
  5. Default -> English

A value of "auto" (the default) triggers detection (steps 2-5). Explicitly
setting "zh" or "en" locks the language and skips detection.
"""

import os
import subprocess
import sys

# Supported language codes
ZH = "zh"
EN = "en"
SUPPORTED = (ZH, EN)
DEFAULT_LANG = EN

# Resolved language cache; None until first resolution.
_resolved_lang = None


def _normalize(raw):
    """Map an arbitrary locale-ish string to a supported code, or None.

    Only Chinese is detected explicitly; everything else (including unknown
    or empty values) yields None so the caller can fall through to the next
    detection source.
    """
    if not raw:
        return None
    value = str(raw).strip().lower().replace("_", "-")
    if value in ("auto", ""):
        return None
    # Chinese variants: zh, zh-cn, zh-hans, zh-hans-cn, zh-tw, zh-hk ...
    if value.startswith("zh") or value.startswith("chinese"):
        return ZH
    if value.startswith("en") or value.startswith("english"):
        return EN
    return None


def _detect_from_env():
    """Detect language from standard locale environment variables.

    Note: on macOS, `LANG` is often a shell default (e.g. en_US.UTF-8 set by
    .zshrc) that does not reflect the user's real preference, so AppleLocale
    is checked first (see detect_language). On Linux these vars are the
    primary signal.

    The cow_lang env override (COW_LANG=zh) is intentionally NOT read here:
    it sets config["cow_lang"] and is handled via the explicit config path,
    not auto-detection.
    """
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        lang = _normalize(os.environ.get(key))
        if lang:
            return lang
    return None


def _detect_from_macos():
    """macOS fallback: read the system-wide AppleLocale preference.

    On macOS the terminal often does NOT export LANG, yet the system locale
    is still meaningful (e.g. a Chinese Mac reports zh_CN). This recovers
    that signal so Chinese users are not misdetected as English.
    """
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["defaults", "read", "-g", "AppleLocale"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return _normalize(out.stdout)
    except Exception:
        pass
    return None


def _detect_from_python_locale():
    """Last-resort detection via Python's locale module."""
    try:
        import locale

        for value in locale.getlocale():
            lang = _normalize(value)
            if lang:
                return lang
    except Exception:
        pass
    return None


def detect_language():
    """Run full auto-detection and return a supported language code.

    Order (auto-detection only; explicit config["cow_lang"] is resolved
    before this is reached):
      1. macOS AppleLocale (system-level preference; a Chinese system locale
         is a strong, low-false-positive signal that beats a shell-default
         LANG like en_US.UTF-8)
      2. locale env vars LC_ALL / LC_MESSAGES / LANG (primary signal on Linux)
      3. Python locale module
      4. default English
    """
    if os.environ.get("CLOUD_DEPLOYMENT_ID"):
        return ZH
    return (
        _detect_from_macos()
        or _detect_from_env()
        or _detect_from_python_locale()
        or DEFAULT_LANG
    )


def resolve_language(configured=None):
    """Resolve the effective language from a configured value.

    `configured` is the raw `cow_lang` value from config.json (may be None,
    "auto", "zh" or "en"). An explicit "zh"/"en" locks the result; "auto"
    or empty triggers detection. The result is cached globally.
    """
    global _resolved_lang
    explicit = _normalize(configured)
    if explicit:
        _resolved_lang = explicit
    else:
        _resolved_lang = detect_language()
    return _resolved_lang


def set_language(lang):
    """Force the resolved language (used by tests or per-request overrides)."""
    global _resolved_lang
    normalized = _normalize(lang)
    _resolved_lang = normalized or DEFAULT_LANG
    return _resolved_lang


def get_language():
    """Return the currently resolved language, detecting lazily if needed."""
    global _resolved_lang
    if _resolved_lang is None:
        _resolved_lang = detect_language()
    return _resolved_lang


def is_zh():
    return get_language() == ZH


def t(zh_text, en_text):
    """Pick a string by the current language. Tiny inline-translation helper.

    Intended for one-off strings where a full message catalog is overkill:
        t("已中止", "Cancelled")
    """
    return zh_text if get_language() == ZH else en_text
