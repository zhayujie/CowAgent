"""
Outbound secret redaction.

Last line of defence. If a secret has somehow reached the reply text - the
agent read a config file it was allowed to read, a stack trace embedded a
connection string, a command echoed an environment variable - this strips it
before the message leaves the machine.

Redaction is applied to what the agent *says*, never to what it reads, so it
cannot break the agent's own reasoning. It is deliberately biased toward
recognisable, high-confidence token shapes: a false positive here mangles a
legitimate reply, so patterns that would match ordinary prose are left out.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple

PLACEHOLDER = "[REDACTED]"

#: (compiled pattern, group index to redact). Group 0 means the whole match.
_PATTERNS: List[Tuple[re.Pattern, int]] = [
    # PEM private key blocks - redact the entire block.
    (re.compile(
        r"-----BEGIN[ A-Z]*PRIVATE KEY-----.*?-----END[ A-Z]*PRIVATE KEY-----",
        re.DOTALL,
    ), 0),
    # Vendor-prefixed API keys with a recognisable shape.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), 0),                    # OpenAI
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"), 0),                # Anthropic
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),                       # AWS access key id
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), 0),                       # AWS temporary key id
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), 0),               # GitHub tokens
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"), 0),                 # GitLab PAT
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), 0),             # Slack
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), 0),                  # Google API key
    (re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}"), 0),                 # Google OAuth
    (re.compile(r"\bAC[a-f0-9]{32}\b"), 0),                         # Twilio SID
    (re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{16,}"), 0),          # Stripe
    (re.compile(r"\bcv[0-9]_[A-Za-z0-9]{16,}"), 0),                 # Feishu/Lark app secret style
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), 0),  # JWT
    # KEY=value assignments in env-file / shell style. Redact only the value.
    (re.compile(
        r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE[_-]?KEY|"
        r"ACCESS[_-]?KEY|CLIENT[_-]?SECRET|AUTH)[A-Z0-9_]*)\s*[:=]\s*[\"']?([^\s\"',;]{6,})"
    ), 2),
    # Credentials embedded in a URL.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@/]{3,})(@)"), 2),
    # Authorization headers.
    (re.compile(r"(?i)(Authorization\s*:\s*(?:Bearer|Basic|Token)\s+)(\S{8,})"), 2),
]


def _redact_with(pattern: re.Pattern, group: int, text: str) -> Tuple[str, int]:
    count = 0

    def _sub(match: re.Match) -> str:
        nonlocal count
        count += 1
        if group == 0:
            return PLACEHOLDER
        whole = match.group(0)
        target = match.group(group)
        if not target:
            return whole
        start = match.start(group) - match.start(0)
        end = match.end(group) - match.start(0)
        return whole[:start] + PLACEHOLDER + whole[end:]

    return pattern.sub(_sub, text), count


def redact(text: str, extra_values: Iterable[str] = ()) -> Tuple[str, int]:
    """Redact secrets in *text*.

    Args:
        text: content about to be sent to a user or a group.
        extra_values: known literal secrets (e.g. values loaded from the
            agent's own .env) to strip verbatim.

    Returns:
        ``(redacted_text, number_of_redactions)``.
    """
    if not text or not isinstance(text, str):
        return text, 0

    total = 0
    for value in extra_values or ():
        value = str(value or "")
        if len(value) >= 8 and value in text:
            text = text.replace(value, PLACEHOLDER)
            total += 1

    for pattern, group in _PATTERNS:
        text, count = _redact_with(pattern, group, text)
        total += count

    return text, total


def redact_text(text: str, extra_values: Iterable[str] = ()) -> str:
    """:func:`redact` without the count, for call sites that do not need it."""
    return redact(text, extra_values)[0]


def known_secret_values() -> List[str]:
    """Literal secret values from the agent's own credential store.

    Reading the file here is intentional and safe: the values are used only to
    remove them from outbound text, never to surface them.
    """
    from common.utils import expand_path
    import os

    values: List[str] = []
    env_file = expand_path("~/.cow/.env")
    if not os.path.exists(env_file):
        return values
    try:
        from dotenv import dotenv_values

        for value in dotenv_values(env_file).values():
            value = str(value or "")
            if len(value) >= 8:
                values.append(value)
    except Exception:
        pass
    return values
