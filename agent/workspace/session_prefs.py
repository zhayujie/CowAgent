"""Per-session runtime preferences: which model answers, what it may change.

Sibling of :mod:`agent.workspace.project_store`, same shape and same key scheme.
A conversation can pin its own model and its own permission mode; anything not
pinned follows the global settings, so an untouched session keeps behaving the
way the instance is configured.

Why a JSON file rather than the sessions table: the web UI mints a session id in
the browser and a row only appears once the first message is persisted. A user
who picks a model before typing must have somewhere to put it, and this store
has no foreign key to satisfy.

Stored under ``<shared_root>/session_prefs.json``::

    {
      "sessions": {
        "default::session_abc": {
          "provider": "claudeAPI",
          "model": "claude-sonnet-5",
          "permission": "workspace-write",
          "ts": 1731999999.0
        }
      }
    }

Every field is optional. Absent means "follow the global setting".
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, Optional

from common.log import logger

_FIELDS = ("provider", "model", "permission")

_lock = threading.Lock()


def _store_file() -> str:
    from common.state_dir import shared_root

    return str(shared_root() / "session_prefs.json")


def _load() -> Dict:
    path = _store_file()
    if not os.path.isfile(path):
        return {"sessions": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception as e:
        logger.warning(f"[SessionPrefs] Could not read {path}: {e}")
        return {"sessions": {}}
    if not isinstance(data.get("sessions"), dict):
        data["sessions"] = {}
    return data


def _save(data: Dict) -> None:
    path = _store_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning(f"[SessionPrefs] Could not write {path}: {e}")


def _session_key(session_id: str, agent_id: Optional[str]) -> str:
    """Namespace by agent so identical session ids across Agents don't collide."""
    return f"{agent_id or 'default'}::{session_id}"


def get_prefs(session_id: str, agent_id: Optional[str] = None) -> Dict:
    """Overrides explicitly set for a session (missing keys = follow global)."""
    if not session_id:
        return {}
    with _lock:
        data = _load()
        entry = data["sessions"].get(_session_key(session_id, agent_id))
    if not isinstance(entry, dict):
        return {}
    return {k: entry[k] for k in _FIELDS if entry.get(k)}


def set_prefs(
    session_id: str,
    agent_id: Optional[str] = None,
    **updates,
) -> Dict:
    """Merge overrides for a session; pass ``None`` for a field to clear it.

    Returns the resulting override dict (empty when the session now follows the
    global settings entirely).
    """
    if not session_id:
        raise ValueError("session_id is required")

    key = _session_key(session_id, agent_id)
    with _lock:
        data = _load()
        entry = data["sessions"].get(key)
        entry = dict(entry) if isinstance(entry, dict) else {}

        for field in _FIELDS:
            if field not in updates:
                continue
            value = updates[field]
            if value is None or (isinstance(value, str) and not value.strip()):
                entry.pop(field, None)
            else:
                entry[field] = value.strip() if isinstance(value, str) else value

        result = {k: entry[k] for k in _FIELDS if entry.get(k)}
        if result:
            data["sessions"][key] = {**result, "ts": time.time()}
        else:
            # Nothing pinned any more: drop the row instead of leaving a husk.
            data["sessions"].pop(key, None)
        _save(data)
    return result


def forget_session(session_id: str, agent_id: Optional[str] = None) -> None:
    """Drop a session's overrides (called when the conversation is deleted)."""
    if not session_id:
        return
    key = _session_key(session_id, agent_id)
    with _lock:
        data = _load()
        if data["sessions"].pop(key, None) is not None:
            _save(data)


def resolve_permission(session_id: str, agent_id: Optional[str] = None) -> str:
    """The permission mode in force for a session: its own, else the global one."""
    from agent.permission import global_mode, normalize_mode

    prefs = get_prefs(session_id, agent_id)
    if prefs.get("permission"):
        return normalize_mode(prefs["permission"], global_mode())
    return global_mode()
