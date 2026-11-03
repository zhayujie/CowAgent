"""SQLite storage for background tasks and the approvals they wait on.

One database for the whole instance (``system/tasks.db``), each row tagged
with the Agent it runs as, like the scheduler's single task file. Schema
changes are limited to adding columns and plain indexes; de-duplication is
done in code inside the same write transaction, never with table constraints.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

from common.log import logger

# Task lifecycle
QUEUED = "queued"
RUNNING = "running"
WAITING = "waiting"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

TASK_STATUSES = (QUEUED, RUNNING, WAITING, DONE, FAILED, CANCELLED)
ACTIVE_STATUSES = (QUEUED, RUNNING, WAITING)
FINISHED_STATUSES = (DONE, FAILED, CANCELLED)

# What a waiting task waits for
WAIT_APPROVAL = "approval"
WAIT_ACCEPT = "accept"

# Where a task came from
SOURCE_MANUAL = "manual"
SOURCE_CHAT = "chat"
SOURCE_SCHEDULE = "schedule"

NOTIFY_LEVELS = ("all", "action_only", "silent")

# Approvals
KIND_ACTION = "action"
KIND_ACCEPT = "accept"

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"

TASK_SESSION_PREFIX = "task_"


def task_session_id(task_id: int) -> str:
    return f"{TASK_SESSION_PREFIX}{task_id}"


def task_id_from_session(session_id: Optional[str]) -> Optional[int]:
    """The task a ``task_<id>`` execution session belongs to, else None."""
    sid = str(session_id or "")
    if not sid.startswith(TASK_SESSION_PREFIX):
        return None
    tail = sid[len(TASK_SESSION_PREFIX):]
    return int(tail) if tail.isdigit() else None


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        prompt TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'queued',
        wait_type TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        schedule_id TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT '{}',
        session_id TEXT NOT NULL DEFAULT '',
        require_accept INTEGER NOT NULL DEFAULT 0,
        notify_level TEXT NOT NULL DEFAULT 'all',
        pending_input TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        run_count INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL DEFAULT 0,
        started_at REAL NOT NULL DEFAULT 0,
        finished_at REAL NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at)",
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        agent_id TEXT NOT NULL DEFAULT '',
        session_id TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT '{}',
        kind TEXT NOT NULL DEFAULT 'action',
        tool_name TEXT NOT NULL DEFAULT '',
        tool_args TEXT NOT NULL DEFAULT '{}',
        args_key TEXT NOT NULL DEFAULT '',
        rule_id TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        decision_note TEXT NOT NULL DEFAULT '',
        decided_via TEXT NOT NULL DEFAULT '',
        exec_result TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL DEFAULT 0,
        decided_at REAL NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status)",
    "CREATE INDEX IF NOT EXISTS idx_approvals_task ON approvals(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id)",
)

# Columns added after the first schema; each is added once if missing.
_ADDED_COLUMNS = (
    ("tasks", "pending_display", "TEXT NOT NULL DEFAULT ''"),
)

_TASK_FIELDS = (
    "agent_id", "title", "prompt", "status", "wait_type", "source", "schedule_id",
    "origin", "session_id", "require_accept", "notify_level", "pending_input",
    "pending_display", "result", "error", "run_count", "created_at", "updated_at", "started_at",
    "finished_at",
)


def args_key(tool_name: str, tool_args: Any) -> str:
    """A stable identity for one tool call: same tool, same arguments."""
    try:
        body = json.dumps(tool_args, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        body = str(tool_args)
    return f"{tool_name}:{body}"


class TaskStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                for stmt in _SCHEMA:
                    conn.execute(stmt)
                for table, column, spec in _ADDED_COLUMNS:
                    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                    if column not in have:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ tasks

    @staticmethod
    def _task_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        task = dict(row)
        try:
            task["origin"] = json.loads(task.get("origin") or "{}")
        except Exception:
            task["origin"] = {}
        task["require_accept"] = bool(task.get("require_accept"))
        return task

    def create_task(
        self,
        title: str,
        prompt: str,
        agent_id: str = "",
        source: str = SOURCE_MANUAL,
        origin: Optional[dict] = None,
        require_accept: bool = False,
        notify_level: str = "all",
        schedule_id: str = "",
        session_id: str = "",
    ) -> Dict[str, Any]:
        now = time.time()
        if notify_level not in NOTIFY_LEVELS:
            notify_level = "all"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO tasks (agent_id, title, prompt, status, source, schedule_id,
                                       origin, require_accept, notify_level,
                                       created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id or "", (title or "").strip(), prompt or "", QUEUED,
                        source, schedule_id or "",
                        json.dumps(origin or {}, ensure_ascii=False),
                        1 if require_accept else 0, notify_level, now, now,
                    ),
                )
                task_id = cur.lastrowid
                conn.execute(
                    "UPDATE tasks SET session_id = ? WHERE id = ?",
                    (session_id or task_session_id(task_id), task_id),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
            finally:
                conn.close()
        return self._task_row(row)

    @staticmethod
    def _task_filter(statuses, agent_id, source, schedule_id=None):
        clauses, params = [], []
        if statuses:
            statuses = list(statuses)
            clauses.append(f"status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if schedule_id:
            clauses.append("schedule_id = ?")
            params.append(str(schedule_id))
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def list_tasks(
        self,
        statuses: Optional[Iterable[str]] = None,
        agent_id: Optional[str] = None,
        limit: int = 200,
        source: Optional[str] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        where, params = self._task_filter(statuses, agent_id, source)
        sql = f"SELECT * FROM tasks{where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([max(1, int(limit)), max(0, int(offset))])
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        return [self._task_row(r) for r in rows]

    def count_tasks(
        self,
        statuses: Optional[Iterable[str]] = None,
        agent_id: Optional[str] = None,
        source: Optional[str] = None,
        schedule_id: Optional[str] = None,
    ) -> int:
        where, params = self._task_filter(statuses, agent_id, source, schedule_id)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM tasks{where}", params).fetchone()
            finally:
                conn.close()
        return int(row[0] if row else 0)

    def update_task(self, task_id: int, expect_status: Optional[Iterable[str]] = None,
                    **fields) -> bool:
        """Update a task; with ``expect_status`` only while it is in one of them.

        The status guard is what keeps two actors from both moving the same
        task: the second one's update matches no row and reports False.
        """
        fields = {k: v for k, v in fields.items() if k in _TASK_FIELDS}
        if not fields:
            return False
        if "origin" in fields and not isinstance(fields["origin"], str):
            fields["origin"] = json.dumps(fields["origin"] or {}, ensure_ascii=False)
        if "require_accept" in fields:
            fields["require_accept"] = 1 if fields["require_accept"] else 0
        fields["updated_at"] = time.time()
        sets = ", ".join(f"{k} = ?" for k in fields)
        params: List[Any] = list(fields.values())
        sql = f"UPDATE tasks SET {sets} WHERE id = ?"
        params.append(int(task_id))
        if expect_status:
            expect_status = list(expect_status)
            sql += f" AND status IN ({','.join('?' * len(expect_status))})"
            params.extend(expect_status)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def append_pending_input(self, task_id: int, text: str, display: str = "") -> None:
        """Queue a message for the task's next run, after any already queued.
        ``display`` is how the message reads in the transcript, when that
        differs from what the Agent is told."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT pending_input, pending_display FROM tasks WHERE id = ?", (int(task_id),)
                ).fetchone()
                if row is None:
                    return
                join = lambda cur, new: f"{cur}\n\n{new}" if cur else new
                conn.execute(
                    "UPDATE tasks SET pending_input = ?, pending_display = ?, updated_at = ? WHERE id = ?",
                    (join(row["pending_input"] or "", text),
                     join(row["pending_display"] or "", display or text),
                     time.time(), int(task_id)),
                )
                conn.commit()
            finally:
                conn.close()

    def take_pending_input(self, task_id: int) -> tuple:
        """Read and clear the queued messages in one step: ``(text, display)``."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT pending_input, pending_display FROM tasks WHERE id = ?", (int(task_id),)
                ).fetchone()
                text = (row["pending_input"] if row else "") or ""
                display = (row["pending_display"] if row else "") or ""
                if text or display:
                    conn.execute("UPDATE tasks SET pending_input = '', pending_display = '' WHERE id = ?",
                                 (int(task_id),))
                    conn.commit()
                return text, display
            finally:
                conn.close()

    def claim_next(self, limit: int, scheduled: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Move up to ``limit`` queued tasks to running; only scheduled ones or
        only the rest when ``scheduled`` says so. A task that has run before
        goes first, since it is back in the queue because someone followed it
        up or decided on it; new tasks then follow, oldest first."""
        if limit <= 0:
            return []
        sql = "SELECT id FROM tasks WHERE status = ?"
        params: List[Any] = [QUEUED]
        if scheduled is not None:
            sql += " AND source = ?" if scheduled else " AND source != ?"
            params.append(SOURCE_SCHEDULE)
        sql += " ORDER BY CASE WHEN run_count > 0 THEN 0 ELSE 1 END, updated_at ASC, id ASC LIMIT ?"
        params.append(int(limit))
        claimed = []
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                now = time.time()
                for row in rows:
                    cur = conn.execute(
                        """
                        UPDATE tasks SET status = ?, wait_type = '', started_at = ?,
                               updated_at = ?, run_count = run_count + 1
                        WHERE id = ? AND status = ?
                        """,
                        (RUNNING, now, now, row["id"], QUEUED),
                    )
                    if cur.rowcount:
                        claimed.append(row["id"])
                conn.commit()
            finally:
                conn.close()
        return [t for t in (self.get_task(tid) for tid in claimed) if t]

    def requeue_interrupted(self) -> int:
        """Tasks left running by a previous process go back to the queue."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE status = ?",
                    (QUEUED, time.time(), RUNNING),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def delete_task(self, task_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
                conn.execute("DELETE FROM approvals WHERE task_id = ?", (int(task_id),))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def count_by_status(self) -> Dict[str, int]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
                ).fetchall()
            finally:
                conn.close()
        counts = {s: 0 for s in TASK_STATUSES}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    # -------------------------------------------------------------- approvals

    @staticmethod
    def _approval_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        appr = dict(row)
        for key, default in (("origin", {}), ("tool_args", {})):
            try:
                appr[key] = json.loads(appr.get(key) or json.dumps(default))
            except Exception:
                appr[key] = default
        appr.pop("args_key", None)
        return appr

    def create_approval(
        self,
        kind: str,
        task_id: Optional[int] = None,
        agent_id: str = "",
        session_id: str = "",
        origin: Optional[dict] = None,
        tool_name: str = "",
        tool_args: Optional[dict] = None,
        rule_id: str = "",
        label: str = "",
        summary: str = "",
    ) -> Dict[str, Any]:
        """Open an approval, or return the pending one for the very same call.

        A model that repeats a gated call while it waits would otherwise file
        a second card for one decision.
        """
        key = args_key(tool_name, tool_args or {}) if kind == KIND_ACTION else ""
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                if kind == KIND_ACTION:
                    existing = conn.execute(
                        """
                        SELECT * FROM approvals
                        WHERE status = ? AND kind = ? AND session_id = ? AND args_key = ?
                        ORDER BY id DESC LIMIT 1
                        """,
                        (PENDING, kind, session_id or "", key),
                    ).fetchone()
                    if existing is not None:
                        return self._approval_row(existing)
                elif task_id is not None:
                    existing = conn.execute(
                        "SELECT * FROM approvals WHERE status = ? AND kind = ? AND task_id = ? "
                        "ORDER BY id DESC LIMIT 1",
                        (PENDING, kind, int(task_id)),
                    ).fetchone()
                    if existing is not None:
                        return self._approval_row(existing)
                cur = conn.execute(
                    """
                    INSERT INTO approvals (task_id, agent_id, session_id, origin, kind,
                                           tool_name, tool_args, args_key, rule_id, label,
                                           summary, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id, agent_id or "", session_id or "",
                        json.dumps(origin or {}, ensure_ascii=False), kind,
                        tool_name or "", json.dumps(tool_args or {}, ensure_ascii=False),
                        key, rule_id or "", label or "", summary or "", PENDING, now,
                    ),
                )
                conn.commit()
                approval_id = cur.lastrowid
            finally:
                conn.close()
        created = self.get_approval(approval_id)
        created["is_new"] = True
        return created

    def get_approval(self, approval_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM approvals WHERE id = ?", (int(approval_id),)
                ).fetchone()
            finally:
                conn.close()
        return self._approval_row(row)

    def list_approvals(
        self,
        status: Optional[str] = None,
        task_id: Optional[int] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM approvals"
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(int(task_id))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        return [self._approval_row(r) for r in rows]

    def count_pending(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute(
                    "SELECT COUNT(*) FROM approvals WHERE status = ?", (PENDING,)
                ).fetchone()[0]
            finally:
                conn.close()

    def pending_for_task(self, task_id: int) -> List[Dict[str, Any]]:
        return self.list_approvals(status=PENDING, task_id=task_id)

    def decide_approval(
        self,
        approval_id: int,
        status: str,
        note: str = "",
        via: str = "",
        tool_args: Optional[dict] = None,
    ) -> bool:
        """Settle a pending approval. False when someone already settled it."""
        sets = "status = ?, decision_note = ?, decided_via = ?, decided_at = ?"
        params: List[Any] = [status, note or "", via or "", time.time()]
        if tool_args is not None:
            sets += ", tool_args = ?"
            params.append(json.dumps(tool_args, ensure_ascii=False))
        params.extend([int(approval_id), PENDING])
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    f"UPDATE approvals SET {sets} WHERE id = ? AND status = ?", params
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def set_exec_result(self, approval_id: int, result: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE approvals SET exec_result = ? WHERE id = ?",
                    (result or "", int(approval_id)),
                )
                conn.commit()
            finally:
                conn.close()

    def expire_for_task(self, task_id: int) -> int:
        """Close every open approval of a task that will not run again."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE approvals SET status = ?, decided_at = ? WHERE task_id = ? AND status = ?",
                    (EXPIRED, time.time(), int(task_id), PENDING),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def recent_decision(self, session_id: str, tool_name: str, tool_args: Any,
                        within_seconds: float = 1800) -> Optional[Dict[str, Any]]:
        """The latest settled decision on this exact call in this session.

        Lets the gate answer a repeated call from what the user already
        decided, so an approved send is never run twice and a rejected one is
        not asked about again.
        """
        if not session_id:
            return None
        key = args_key(tool_name, tool_args or {})
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT * FROM approvals
                    WHERE session_id = ? AND args_key = ? AND status IN (?, ?)
                          AND decided_at >= ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (session_id, key, APPROVED, REJECTED, time.time() - within_seconds),
                ).fetchone()
            finally:
                conn.close()
        return self._approval_row(row)


_store: Optional[TaskStore] = None
_store_lock = threading.Lock()


def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                from common.state_dir import system_dir

                path = str(system_dir(ensure=True) / "tasks.db")
                _store = TaskStore(path)
                logger.debug(f"[Task] Store opened: {path}")
    return _store

