"""
Inline memory-entry annotations

Lightweight markers embedded at the start of MEMORY.md entries, e.g.

    - [2026-03-08|conf:high|src:dialog] User prefers concave answers

They carry provenance metadata (date, confidence, source) that Deep Dream
uses when distilling memory. Markers are display/provenance data, not
content: they are stripped before chunking so they never reach embeddings,
stored chunk text, or retrieval snippets.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# One inline marker: [YYYY-MM-DD|conf:high|src:dialog]
MARKER_PATTERN = re.compile(
    r"\[\d{4}-\d{2}-\d{2}\|conf:(?:high|mid|low)\|src:[a-z0-9-]+\]"
)

VALID_CONFIDENCES = ("high", "mid", "low")


def format_memory_marker(
    date_str: str, confidence: str = "mid", source: str = "dialog"
) -> str:
    """Build an inline marker. Unknown confidence levels fall back to mid."""
    conf = confidence if confidence in VALID_CONFIDENCES else "mid"
    return f"[{date_str}|conf:{conf}|src:{source}]"


def parse_memory_marker(text: str) -> Optional[Dict[str, Any]]:
    """Read the first marker in *text*, or None when it carries none."""
    match = MARKER_PATTERN.search(text)
    if not match:
        return None
    marker = match.group(0).strip("[]")
    date_str, conf_part, src_part = marker.split("|")
    return {
        "date": date_str,
        "confidence": conf_part.split(":", 1)[1],
        "source": src_part.split(":", 1)[1],
    }


# Strip variant: also removes the single space separating the marker from
# the entry text, so "- [marker] text" becomes "- text".
_STRIP_PATTERN = re.compile(MARKER_PATTERN.pattern + r" ?")


def strip_memory_markers(text: str) -> str:
    """Remove inline markers (plus one trailing space) from every line.

    Markers sit inline at the start of an entry, so a plain substitution
    keeps the line structure — and therefore chunk line numbers — intact.
    """
    return _STRIP_PATTERN.sub("", text)
