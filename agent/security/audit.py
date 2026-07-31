"""
Security audit trail.

Every refusal, and every sensitive call that was allowed, is recorded. Two
sinks are used deliberately:

* the normal application logger, so a denial is visible right next to the
  request that caused it while debugging;
* an append-only JSONL file under the agent workspace, so the record survives
  log rotation and can be reviewed after the fact - "did anything odd get asked
  of my bot while I was away" is the question this answers.

Writes never raise. An audit failure must not take down the request it was
auditing.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

from common.log import logger

_lock = threading.Lock()
_LOG_NAME = "security_audit.jsonl"
#: Rotate at 5 MB so the file cannot grow without bound.
_MAX_BYTES = 5 * 1024 * 1024


def _audit_path() -> Optional[str]:
    from common.utils import expand_path
    from config import conf

    if not conf().get("security_audit_log", True):
        return None
    try:
        workspace = expand_path(conf().get("agent_workspace", "~/cow") or "~/cow")
        directory = os.path.join(workspace, "logs")
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, _LOG_NAME)
    except Exception:
        return None


def _rotate(path: str) -> None:
    try:
        if os.path.exists(path) and os.path.getsize(path) > _MAX_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass


def _truncate(value: Any, limit: int = 500) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"...(+{len(value) - limit} chars)"
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_truncate(v, limit) for v in value[:20]]
    return value


def record(
    event: str,
    ctx: Any = None,
    outcome: str = "",
    tool: str = "",
    category: str = "",
    detail: Optional[dict] = None,
) -> None:
    """Append one audit entry. Never raises."""
    try:
        from agent.security.trust import current_security_context

        ctx = ctx or current_security_context()
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            "outcome": outcome,
            "tool": tool,
            "category": category,
            "trust": getattr(getattr(ctx, "trust", None), "label", "unknown"),
            "user_id": getattr(ctx, "user_id", ""),
            "nickname": getattr(ctx, "nickname", ""),
            "channel": getattr(ctx, "channel", ""),
            "is_group": getattr(ctx, "is_group", False),
            "group": getattr(ctx, "group_name", "") or getattr(ctx, "group_id", ""),
            "session_id": getattr(ctx, "session_id", ""),
            "detail": _truncate(detail or {}),
        }
    except Exception:  # pragma: no cover - defensive
        return

    if outcome == "denied":
        logger.warning(
            f"[Security] DENIED {tool or event} ({category}) for "
            f"{entry['nickname'] or entry['user_id'] or 'unknown'} "
            f"[{entry['trust']}] in {'group ' + str(entry['group']) if entry['is_group'] else 'private chat'}"
        )
    else:
        logger.debug(f"[Security] {outcome or 'event'} {tool or event} ({category})")

    path = _audit_path()
    if not path:
        return
    try:
        with _lock:
            _rotate(path)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"[Security] Failed to write audit entry: {e}")


def record_denial(tool: str, category: str, ctx: Any = None, **detail) -> None:
    record("tool_call", ctx=ctx, outcome="denied", tool=tool, category=category, detail=detail)


def record_confirmation(tool: str, category: str, ctx: Any = None, **detail) -> None:
    record("tool_call", ctx=ctx, outcome="needs_confirmation", tool=tool, category=category, detail=detail)


def record_injection(source: str, findings: Any, ctx: Any = None) -> None:
    record(
        "injection_detected",
        ctx=ctx,
        outcome="flagged",
        tool=source,
        category="injection",
        detail={"findings": [str(f) for f in (findings or [])]},
    )


def record_redaction(count: int, ctx: Any = None) -> None:
    if count > 0:
        record("outbound_redaction", ctx=ctx, outcome="redacted", category="redaction",
               detail={"count": count})
