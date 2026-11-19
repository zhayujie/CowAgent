"""Decode subprocess output.

On Chinese Windows many built-in commands (`date`, `dir`, ...) emit CP936/GBK
bytes even after `chcp 65001`, so a plain UTF-8 decode turns them into mojibake
like `ϵͳ�޷�`. Try UTF-8 first, then fall back to the console/locale encoding
when UTF-8 produces replacement characters.
"""

import sys


def _fallback_encoding() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import locale
        # In Python's UTF-8 mode (PYTHONUTF8=1 / -X utf8, and the default from
        # Python 3.15) getpreferredencoding() always returns "utf-8", which
        # would skip the fallback. getencoding() (3.11+) still returns the
        # Windows code page.
        getencoding = getattr(locale, "getencoding", None)
        if getencoding is not None:
            return getencoding() or "gbk"
        return locale.getpreferredencoding(False) or "gbk"
    except Exception:
        return "gbk"


def decode_output(data: bytes) -> str:
    if not data:
        return ""
    try:
        text = data.decode("utf-8")
        if "\ufffd" not in text:
            return text
        strict = text
    except UnicodeDecodeError:
        strict = None

    enc = _fallback_encoding()
    if enc and enc.lower() not in ("utf-8", "utf8"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass

    return strict if strict is not None else data.decode("utf-8", errors="replace")
