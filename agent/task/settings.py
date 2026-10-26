"""The ``task`` section of config.json: background tasks, approvals, notices.

Everything defaults to off. With ``enabled`` false nothing in this package
runs: no tool is offered, no rule is checked and scheduled tasks keep their
old path.
"""

from __future__ import annotations

import copy
import hashlib
import threading
from typing import Any, Dict, List

from common.log import logger

CONFIG_KEY = "task"

DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "chat_create": False,
    "max_concurrency": 2,
    "notify_webhook": "",
    "approval_rules": [],
}

RULE_ACTIONS = ("ask", "deny")
MAX_CONCURRENCY_RANGE = (1, 10)

_save_lock = threading.Lock()


def task_settings() -> Dict[str, Any]:
    """The effective settings, defaults filled in for anything absent."""
    try:
        from config import conf

        raw = conf().get(CONFIG_KEY)
    except Exception:
        raw = None
    merged = copy.deepcopy(DEFAULTS)
    if isinstance(raw, dict):
        for key in DEFAULTS:
            if key in raw:
                merged[key] = raw[key]
    merged["enabled"] = bool(merged.get("enabled"))
    merged["chat_create"] = bool(merged.get("chat_create"))
    merged["max_concurrency"] = _clamp_concurrency(merged.get("max_concurrency"))
    merged["notify_webhook"] = str(merged.get("notify_webhook") or "").strip()
    merged["approval_rules"] = normalize_rules(merged.get("approval_rules"))
    return merged


def is_enabled() -> bool:
    try:
        from config import conf

        raw = conf().get(CONFIG_KEY)
    except Exception:
        return False
    return isinstance(raw, dict) and bool(raw.get("enabled"))


def _clamp_concurrency(value) -> int:
    lo, hi = MAX_CONCURRENCY_RANGE
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULTS["max_concurrency"]
    return max(lo, min(hi, n))


def normalize_rules(raw) -> List[Dict[str, Any]]:
    """Coerce whatever the file or the API holds into well-formed rules.

    A rule without a tool pattern can never match and is dropped; an unknown
    action falls back to ``ask``, the safe one of the two.
    """
    if not isinstance(raw, list):
        return []
    rules = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        if not tool:
            continue
        action = str(item.get("action") or "ask").strip().lower()
        if action not in RULE_ACTIONS:
            action = "ask"
        match = str(item.get("match") or "").strip()
        # A rule written by hand has no id; derive one from its content so
        # it stays the same across reads and approvals can point back at it.
        rule_id = str(item.get("id") or "").strip() or _content_id(tool, match, action)
        suffix = 1
        base_id = rule_id
        while rule_id in seen:
            suffix += 1
            rule_id = f"{base_id}-{suffix}"
        seen.add(rule_id)
        rules.append({
            "id": rule_id,
            "tool": tool,
            "match": match,
            "action": action,
            "label": str(item.get("label") or "").strip(),
            "enabled": item.get("enabled", True) is not False,
        })
    return rules


def _content_id(tool: str, match: str, action: str) -> str:
    return hashlib.sha1(f"{tool}\n{match}\n{action}".encode("utf-8")).hexdigest()[:8]


def save_task_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``updates`` into the ``task`` section, persist it, publish it.

    The file is written first and the live config updated after, so a failed
    write changes nothing.
    """
    from config import conf, get_data_root
    import os

    from channel.web.core._common import (
        _read_config_file_for_write,
        _write_config_file_for_write,
    )

    with _save_lock:
        current = task_settings()
        if "enabled" in updates:
            current["enabled"] = bool(updates["enabled"])
        if "max_concurrency" in updates:
            current["max_concurrency"] = _clamp_concurrency(updates["max_concurrency"])
        if "notify_webhook" in updates:
            current["notify_webhook"] = str(updates["notify_webhook"] or "").strip()
        if "approval_rules" in updates:
            current["approval_rules"] = normalize_rules(updates["approval_rules"])

        file_cfg = _read_config_file_for_write()
        section = dict(file_cfg.get(CONFIG_KEY) or {})
        section.update(current)
        file_cfg[CONFIG_KEY] = section
        _write_config_file_for_write(os.path.join(get_data_root(), "config.json"), file_cfg)
        conf()[CONFIG_KEY] = section
        logger.info(f"[Task] Settings updated: {sorted(updates.keys())}")
        return task_settings()


def disable_rule(rule_id: str) -> bool:
    """Switch one approval rule off ("auto-approve this kind from now on")."""
    if not rule_id:
        return False
    rules = task_settings()["approval_rules"]
    changed = False
    for rule in rules:
        if rule["id"] == rule_id and rule["enabled"]:
            rule["enabled"] = False
            changed = True
    if changed:
        save_task_settings({"approval_rules": rules})
    return changed
