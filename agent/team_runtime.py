"""The shared team runtime: mailbox, task board, activity feed.

A team conversation (the leader plus its teammates) gets one runtime store
that everyone reads and writes: agents through the ``team_send``/
``team_inbox``/``team_task`` tools, the web console through
``channel/web/api/team.py``.

The store lives under ``common.state_dir.team_runtime_dir()``, keyed by team
id (the team conversation's session id), so a message the leader sends is the
same record a teammate reads regardless of whose workspace the conversation
runs in — ownership sits on the records (``from_id``/``to_id``), never in the
path.

Three files per team, each a JSON list, written atomically under a per-team
lock:

- ``mailbox.json``  — messages with read receipts (only the recipient may
  mark one read, exactly like AionUi's team mailbox).
- ``tasks.json``    — task board entries with owner and ``blocked_by``
  dependencies; a cycle in the dependency graph is rejected at write time.
- ``activity.json`` — one unified feed of everything that happened in the
  team, newest first with keyset pagination for the console's feed view.

All three are pruned to the configured caps (``team_collab`` in config), so a
long-lived team never grows a store it has to load in full.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from common.log import logger
from common.state_dir import team_runtime_dir

# The message kinds AionUi's mailbox uses; "result" carries a completed piece
# of work back to whoever asked, "question" blocks on a reply.
MESSAGE_TYPES = ("info", "question", "result")

# AionUi's task lifecycle. "blocked" is deliberately not a status: blockedness
# is a *fact* derived from a task's unfinished ``blocked_by`` dependencies.
TASK_STATUSES = ("pending", "in_progress", "completed")

ACTIVITY_KINDS = ("message", "task")

MAX_MESSAGE_CHARS_HARD = 100_000
DEFAULT_MAILBOX_PRUNE = 200
DEFAULT_TASK_PRUNE = 200
DEFAULT_ACTIVITY_PRUNE = 500


class TeamRuntimeError(RuntimeError):
    """A team runtime call could not be carried out (bad task, cycle, …)."""


def iso(ts: float) -> str:
    """Display timestamp for a stored epoch value."""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def cursor_of(item: dict) -> str:
    """Opaque keyset cursor for one feed item: ``<ts>|<id>``."""
    return f"{float(item.get('ts', 0.0)):.6f}|{item.get('id', '')}"


@dataclass
class CollabPolicy:
    """Effective ``team_collab`` settings, clamped to sane ranges."""

    wake_on_message: bool = True
    max_wake_depth: int = 2
    max_message_chars: int = 8000
    max_mailbox_messages: int = DEFAULT_MAILBOX_PRUNE
    max_tasks: int = DEFAULT_TASK_PRUNE

    @classmethod
    def from_config(cls, raw) -> "CollabPolicy":
        if raw is False:
            return cls(wake_on_message=False)
        if not isinstance(raw, dict):
            raw = {}

        def _int(key: str, default: int, low: int, high: int) -> int:
            try:
                value = int(raw.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(low, min(value, high))

        return cls(
            wake_on_message=bool(raw.get("wake_on_message", True)),
            max_wake_depth=_int("max_wake_depth", 2, 1, 5),
            max_message_chars=_int("max_message_chars", 8000, 200, MAX_MESSAGE_CHARS_HARD),
            max_mailbox_messages=_int(
                "max_mailbox_messages", DEFAULT_MAILBOX_PRUNE, 10, 10_000
            ),
            max_tasks=_int("max_tasks", DEFAULT_TASK_PRUNE, 10, 10_000),
        )


class TeamStore:
    """Per-team JSON stores under one root, one lock per (team, file)."""

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else team_runtime_dir()
        self._locks: Dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, team_id: str, name: str) -> threading.RLock:
        key = f"{self.root.resolve()}::{team_id}::{name}"
        with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]

    def _team_dir(self, team_id: str) -> Path:
        safe = str(team_id or "team").strip() or "team"
        # Session ids are filename-safe already; refuse anything that would
        # escape the directory rather than sanitize silently.
        if "/" in safe or "\\" in safe or safe in (".", ".."):
            raise TeamRuntimeError(f"bad team id: {team_id!r}")
        return self.root / safe

    def _path(self, team_id: str, name: str) -> Path:
        return self._team_dir(team_id) / name

    def _read(self, team_id: str, name: str) -> List[dict]:
        path = self._path(team_id, name)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            logger.warning(f"[TeamRuntime] unreadable {path.name} for {team_id}: {e}")
            return []
        return raw if isinstance(raw, list) else []

    def _write(self, team_id: str, name: str, items: List[dict]) -> None:
        path = self._path(team_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def _update(self, team_id: str, name: str, mutate) -> List[dict]:
        """Read-modify-write one team file under its per-team lock."""
        with self._lock(team_id, name):
            result = mutate(self._read(team_id, name))
            if result is not None:
                self._write(team_id, name, result)
            return self._read(team_id, name)


    # ---- mailbox ----------------------------------------------------------

    def post_message(
        self,
        team_id: str,
        sender_id: str,
        sender_name: str,
        recipients: List[dict],
        content: str,
        summary: str = "",
        msg_type: str = "info",
        files: Optional[List[str]] = None,
        prune_limit: int = DEFAULT_MAILBOX_PRUNE,
    ) -> List[dict]:
        """Store one message per recipient and return the stored records.

        One record per recipient keeps per-recipient read receipts honest: a
        broadcast is not "read" until every recipient read *their* copy."""
        content = str(content or "").strip()
        if not content:
            raise TeamRuntimeError("message content is required")
        msg_type = msg_type if msg_type in MESSAGE_TYPES else "info"
        now = time.time()
        records = []
        for recipient in recipients or []:
            records.append(
                {
                    "id": new_id(),
                    "team_id": team_id,
                    "kind": "message",
                    "msg_type": msg_type,
                    "from_id": str(sender_id or ""),
                    "from_name": str(sender_name or sender_id or ""),
                    "to_id": str(recipient.get("id", "")),
                    "to_name": str(recipient.get("name", ""))
                    or str(recipient.get("id", "")),
                    "content": content,
                    "summary": str(summary or "").strip(),
                    "files": [str(f) for f in (files or []) if str(f).strip()],
                    "read": False,
                    "ts": now,
                    "created_at": iso(now),
                }
            )
        if not records:
            raise TeamRuntimeError(
                "no recipient given (use a teammate id/name or 'all')"
            )

        def _append(existing):
            return (existing + records)[-prune_limit:] if prune_limit else existing + records

        self._update(team_id, "mailbox.json", _append)
        return records

    def list_messages(
        self,
        team_id: str,
        to_id: Optional[str] = None,
        unread_only: bool = False,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Messages for one team, newest first; ``to_id`` scopes to a mailbox."""
        items = self._read(team_id, "mailbox.json")
        if to_id is not None:
            items = [m for m in items if m.get("to_id") == str(to_id)]
        if unread_only:
            items = [m for m in items if not m.get("read")]
        items = sorted(
            items, key=lambda m: (float(m.get("ts", 0.0)), m.get("id", "")), reverse=True
        )
        return items[:limit] if limit else items

    def get_message(self, team_id: str, message_id: str) -> Optional[dict]:
        for m in self._read(team_id, "mailbox.json"):
            if m.get("id") == message_id:
                return m
        return None

    def mark_messages_read(
        self, team_id: str, recipient_id: str, ids: Optional[List[str]] = None
    ) -> int:
        """Mark ``recipient_id``'s messages read; returns how many changed.

        Receipts belong to the recipient: nobody else — not the sender, not a
        bystander — may flip someone's unread flag, so the filter matches on
        ``to_id`` and the caller passes the ids it just read."""
        wanted = {str(i) for i in (ids or [])}
        before = {
            m.get("id"): bool(m.get("read"))
            for m in self._read(team_id, "mailbox.json")
        }

        def _mark(existing):
            for m in existing:
                if m.get("to_id") != str(recipient_id) or m.get("read"):
                    continue
                if wanted and m.get("id") not in wanted:
                    continue
                m["read"] = True
                m["read_at"] = iso(time.time())
            return existing

        self._update(team_id, "mailbox.json", _mark)
        return sum(
            1
            for m in self._read(team_id, "mailbox.json")
            if m.get("read") and not before.get(m.get("id"), False)
        )

    def unread_count(self, team_id: str, agent_id: str) -> int:
        return len(self.list_messages(team_id, to_id=agent_id, unread_only=True))


    # ---- task board -------------------------------------------------------

    def create_task(
        self,
        team_id: str,
        subject: str,
        description: str = "",
        owner: Optional[dict] = None,
        blocked_by: Optional[List[str]] = None,
        created_by_id: str = "",
        created_by_name: str = "",
        prune_limit: int = DEFAULT_TASK_PRUNE,
    ) -> dict:
        subject = str(subject or "").strip()
        if not subject:
            raise TeamRuntimeError("task subject is required")
        now = time.time()
        task = {
            "id": new_id(),
            "team_id": team_id,
            "subject": subject,
            "description": str(description or "").strip(),
            "status": "pending",
            "owner": str((owner or {}).get("id", "")),
            "owner_name": str((owner or {}).get("name", "")) or str((owner or {}).get("id", "")),
            "blocked_by": [],
            "blocks": [],
            "created_by": str(created_by_id),
            "created_by_name": str(created_by_name or created_by_id),
            "ts": now,
            "created_at": iso(now),
            "updated_at": iso(now),
        }

        def _append(existing):
            existing.append(task)
            return existing

        self._update(team_id, "tasks.json", _append)
        if blocked_by:
            self._relink_dependencies(team_id, task["id"], blocked_by)
        self.prune_tasks(team_id, keep=prune_limit)
        return self.get_task(team_id, task["id"])

    def _relink_dependencies(self, team_id: str, task_id: str, blocked_by: List[str]) -> None:
        """Replace a task's dependency set, re-validating the graph.

        A cycle would deadlock the board: nobody could ever start the task.
        Walk dependencies from the edited task; a path back to it means the
        graph is already tangled without this edge."""
        wanted = [str(b).strip() for b in (blocked_by or []) if str(b).strip()]

        def _apply(existing):
            ids = {t.get("id") for t in existing}
            if task_id not in ids:
                raise TeamRuntimeError(f"unknown task id: {task_id}")
            deps = sorted({d for d in wanted if d in ids and d != task_id})
            graph = {t.get("id"): list(t.get("blocked_by", [])) for t in existing}
            graph[task_id] = deps
            seen, stack = set(), list(deps)
            while stack:
                current = stack.pop()
                if current == task_id:
                    raise TeamRuntimeError(
                        "task dependency cycle: the new blockers (transitively) "
                        "depend on this task"
                    )
                if current in seen:
                    continue
                seen.add(current)
                stack.extend(graph.get(current, []))

            for t in existing:
                if t.get("id") == task_id:
                    t["blocked_by"] = deps
                    t["updated_at"] = iso(time.time())
                blocks = set(t.get("blocks", []))
                blocks.discard(task_id)
                if t.get("id") in deps:
                    blocks.add(task_id)
                t["blocks"] = sorted(blocks)
            return existing

        self._update(team_id, "tasks.json", _apply)


    def get_task(self, team_id: str, task_id: str) -> Optional[dict]:
        for t in self._read(team_id, "tasks.json"):
            if t.get("id") == str(task_id):
                return t
        return None

    def list_tasks(
        self,
        team_id: str,
        status: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> List[dict]:
        items = self._read(team_id, "tasks.json")
        if status:
            items = [t for t in items if t.get("status") == status]
        if owner:
            items = [t for t in items if t.get("owner") == str(owner)]
        # Board order: unfinished work oldest-first, finished last.
        return sorted(
            items,
            key=lambda t: (
                t.get("status") == "completed",
                float(t.get("ts", 0.0)),
                t.get("id", ""),
            ),
        )

    def update_task(self, team_id: str, task_id: str, updates: dict) -> dict:
        """Apply allowed field updates; returns the updated task."""
        task_id = str(task_id)
        status = updates.get("status")
        if status is not None and status not in TASK_STATUSES:
            raise TeamRuntimeError(
                f"unknown task status {status!r}; use one of {', '.join(TASK_STATUSES)}"
            )
        if updates.get("subject") is not None and not str(updates["subject"]).strip():
            raise TeamRuntimeError("task subject cannot be empty")
        if self.get_task(team_id, task_id) is None:
            raise TeamRuntimeError(f"unknown task id: {task_id}")

        def _mutate(existing):
            for t in existing:
                if t.get("id") != task_id:
                    continue
                if updates.get("subject") is not None:
                    t["subject"] = str(updates["subject"]).strip()
                if updates.get("description") is not None:
                    t["description"] = str(updates["description"]).strip()
                if status is not None:
                    t["status"] = status
                if updates.get("owner") is not None:
                    t["owner"] = str(updates["owner"])
                if updates.get("owner_name") is not None:
                    t["owner_name"] = str(updates["owner_name"])
                t["updated_at"] = iso(time.time())
            return existing

        self._update(team_id, "tasks.json", _mutate)
        if updates.get("blocked_by") is not None:
            self._relink_dependencies(team_id, task_id, updates["blocked_by"])
        return self.get_task(team_id, task_id)

    def is_blocked(self, team_id: str, task: dict) -> bool:
        """A task is blocked while any of its blockers is not completed."""
        blockers = task.get("blocked_by") or []
        if not blockers:
            return False
        by_id = {t.get("id"): t for t in self._read(team_id, "tasks.json")}
        return any(
            b not in by_id or by_id[b].get("status") != "completed" for b in blockers
        )

    def prune_tasks(self, team_id: str, keep: int = DEFAULT_TASK_PRUNE) -> int:
        """Cap the board: drop oldest completed tasks first, then oldest overall."""
        with self._lock(team_id, "tasks.json"):
            items = self._read(team_id, "tasks.json")
            if len(items) <= keep:
                return 0
            ordered = sorted(
                items,
                key=lambda t: (t.get("status") != "completed", float(t.get("ts", 0.0))),
            )
            to_drop = {t.get("id") for t in ordered[: len(items) - keep]}
            survivors = [t for t in items if t.get("id") not in to_drop]
            self._write(team_id, "tasks.json", survivors)
            return len(to_drop)


    # ---- activity feed ----------------------------------------------------

    def append_activity(
        self,
        team_id: str,
        kind: str,
        actor_id: str,
        actor_name: str,
        text: str,
        detail: Optional[dict] = None,
        prune_limit: int = DEFAULT_ACTIVITY_PRUNE,
    ) -> dict:
        if kind not in ACTIVITY_KINDS:
            kind = "message"
        now = time.time()
        record = {
            "id": new_id(),
            "team_id": team_id,
            "kind": kind,
            "actor": str(actor_id or ""),
            "actor_name": str(actor_name or actor_id or ""),
            "text": str(text or "").strip(),
            "detail": detail or {},
            "ts": now,
            "created_at": iso(now),
        }

        def _append(existing):
            return (existing + [record])[-prune_limit:] if prune_limit else existing + [record]

        self._update(team_id, "activity.json", _append)
        return record

    def get_activity(
        self, team_id: str, cursor: Optional[str] = None, limit: int = 50
    ) -> dict:
        """Keyset-paginated feed, newest first.

        ``cursor`` is the previous page's last item cursor (``<ts>|<id>``);
        the response carries ``next_cursor`` or None when the feed is
        exhausted, so the console can page forever without offsets shifting
        underneath it."""
        try:
            limit = max(1, min(int(limit or 50), 200))
        except (TypeError, ValueError):
            limit = 50
        items = sorted(
            self._read(team_id, "activity.json"),
            key=lambda a: (float(a.get("ts", 0.0)), a.get("id", "")),
            reverse=True,
        )
        if cursor:
            try:
                raw_ts, raw_id = str(cursor).split("|", 1)
                bound = (float(raw_ts), raw_id)
                items = [
                    a
                    for a in items
                    if (float(a.get("ts", 0.0)), a.get("id", "")) < bound
                ]
            except (TypeError, ValueError):
                pass
        page = items[:limit]
        return {
            "items": page,
            "next_cursor": cursor_of(page[-1]) if len(items) > limit and page else None,
        }


_STORE: Optional[TeamStore] = None
_STORE_LOCK = threading.Lock()


def get_team_store() -> TeamStore:
    """Process-wide store; every reader and writer shares one instance."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = TeamStore()
        return _STORE


def resolve_team_scope(roster: List[dict], self_agent_id: str) -> dict:
    """Validate a roster into something the tools can address.

    ``roster`` is ``{id, name}`` entries, host first (team_addressing's
    shape). A conversation of one is not a team and the tools refuse it with
    the reason, the same way agent_delegate does."""
    entries = [r for r in (roster or []) if str(r.get("id", "")).strip()]
    if len(entries) < 2:
        raise TeamRuntimeError(
            "this conversation has no teammates yet, so there is nobody to "
            "message or share a task board with"
        )
    ids: List[str] = []
    for entry in entries:
        if entry["id"] not in ids:
            ids.append(entry["id"])
    return {"ids": ids, "roster": entries, "self": str(self_agent_id or "")}


def resolve_recipient(value: str, roster: List[dict], self_agent_id: str) -> List[dict]:
    """Resolve one ``to`` value into recipient entries.

    Accepts a teammate id, a (case-insensitive) name, or ``all``/``team`` for
    a broadcast to everyone else on the team. An unknown name raises with the
    valid options, mirroring agent_delegate's error style."""
    value = str(value or "").strip()
    if not value:
        raise TeamRuntimeError("no recipient given (use a teammate id/name or 'all')")
    lowered = value.lower()
    if lowered in ("all", "team", "everyone", "broadcast"):
        return [r for r in roster if r.get("id") != self_agent_id]
    matches = [r for r in roster if r.get("id") == value]
    if not matches:
        matches = [r for r in roster if str(r.get("name", "")).lower() == lowered]
    matches = [r for r in matches if r.get("id") != self_agent_id]
    if not matches:
        others = [
            f"{r.get('name', '')} ({r.get('id')})"
            for r in roster
            if r.get("id") != self_agent_id
        ]
        raise TeamRuntimeError(
            f"'{value}' is not a teammate you can message. Team members: "
            + (", ".join(others) if others else "none besides you")
        )
    return matches


def resolve_agent_ref(value: str, roster: List[dict]) -> Optional[dict]:
    """Owner/actor resolution for the task board: id or (case-insensitive)
    name. ``me`` returns None here; callers substitute themselves first."""
    value = str(value or "").strip()
    if not value or value.lower() == "me":
        return None
    for r in roster:
        if r.get("id") == value:
            return r
    lowered = value.lower()
    for r in roster:
        if str(r.get("name", "")).lower() == lowered:
            return r
    return None