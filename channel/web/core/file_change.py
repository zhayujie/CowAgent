# encoding:utf-8
"""
Turn an edit/write tool result into the file diff the console renders.

The tools already return ``path`` and a unified ``diff``. The SSE handler
used to stringify the whole dict and cut it at 2000 characters, so the diff
never reached the page. This keeps the short message in ``result`` and
carries the diff beside it, with the same budget as a tool's display text.
"""

from __future__ import annotations

import json
from typing import Any, Optional

# Same ceiling as MAX_DISPLAY_STREAM_CHARS in the web SSE callback.
MAX_FILE_DIFF_CHARS = 32 * 1024


def _as_mapping(result: Any) -> Optional[dict]:
    if isinstance(result, dict):
        return result
    if not isinstance(result, str):
        return None
    text = result.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _looks_like_unified_diff(text: str) -> bool:
    for line in text.splitlines()[:12]:
        if line.startswith(("---", "+++", "@@", "+", "-")):
            return True
    return False


def present_tool_result(result: Any, limit: int = MAX_FILE_DIFF_CHARS):
    """
    Split a tool result into the short text the step shows and, when the
    tool edited a file, a structured diff the UI can render on its own.

    Returns ``(result_text, file_change)``. ``file_change`` is None when
    there is nothing to draw. ``result_text`` is still capped by the caller.
    """
    payload = _as_mapping(result)
    if payload is None:
        return str(result if result is not None else ""), None

    diff = payload.get("diff")
    path = payload.get("path")
    if (
        not isinstance(diff, str)
        or not isinstance(path, str)
        or not path
        or not _looks_like_unified_diff(diff)
    ):
        # Leave every other tool on the text it already produced.
        return result if isinstance(result, str) else str(result), None

    truncated = len(diff) > limit
    change = {
        "path": path,
        "diff": diff[:limit] if truncated else diff,
        "truncated": truncated,
    }
    first = payload.get("first_changed_line")
    if isinstance(first, int):
        change["first_changed_line"] = first
    return _summary_text(payload), change


def _summary_text(payload: dict) -> str:
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message
    slim = {key: value for key, value in payload.items() if key != "diff"}
    try:
        return json.dumps(slim, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(slim)
