"""Server-side state of guest shares, in ``<workspace>/guests/data/``.

- ``secret.key``  HMAC key for visitor tokens and signed file links
- ``guest.db``    SQLite: shares, conversations, transcripts, daily usage
- ``sessions/``   visitor work directories, removed when a session expires

``data`` sits beside the profiles, so it is a reserved profile id. A visitor's
Agent never reaches it: its tools only see the session's own mounts, and
``policy`` refuses any reference directory inside ``guests/``.

Tables carry no UNIQUE or composite keys. Each "one row per ..." rule is
checked in code inside the same write transaction, and lookups go through
plain indexes, so the schema only ever grows by ADD COLUMN and CREATE INDEX.

- ``guest_shares``    per profile: share token, password hash, epoch, the
                      configuration the owner last confirmed, switched off
- ``guest_sessions``  per conversation: visitor, title, activity, deletion
- ``guest_messages``  transcript records in order
- ``guest_usage``     questions and tokens per profile, day and visitor

Visitor tokens are stateless and signed over the profile's share token,
password hash and epoch, so resetting the link, changing the password or
revoking sessions invalidates every token issued before.

A token names a visitor, not a conversation. A visitor's session ids start
with their visitor id, so owning a session is a prefix check.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Iterator, List, Optional

from common.log import logger
from common.utils import constant_time_equals

_lock = threading.RLock()
_TOKEN_PREFIX = "g1"
_PBKDF2_ROUNDS = 200_000
DB_FILE = "guest.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guest_shares (
    id            INTEGER PRIMARY KEY,
    slug          TEXT NOT NULL,
    share_token   TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    epoch         INTEGER NOT NULL DEFAULT 1,
    confirmed     TEXT NOT NULL DEFAULT '',
    confirmed_at  REAL NOT NULL DEFAULT 0,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL DEFAULT 0,
    updated_at    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_guest_shares_slug ON guest_shares(slug);
CREATE INDEX IF NOT EXISTS idx_guest_shares_token ON guest_shares(share_token);

CREATE TABLE IF NOT EXISTS guest_sessions (
    id            INTEGER PRIMARY KEY,
    slug          TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    visitor_id    TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    last_question TEXT NOT NULL DEFAULT '',
    questions     INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL DEFAULT 0,
    updated_at    REAL NOT NULL DEFAULT 0,
    deleted_at    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_guest_sessions_sid ON guest_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_guest_sessions_slug ON guest_sessions(slug, updated_at);
CREATE INDEX IF NOT EXISTS idx_guest_sessions_visitor ON guest_sessions(slug, visitor_id, updated_at);

CREATE TABLE IF NOT EXISTS guest_messages (
    id         INTEGER PRIMARY KEY,
    slug       TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    extras     TEXT NOT NULL DEFAULT '',
    tokens     INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_guest_messages_session ON guest_messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_guest_messages_slug ON guest_messages(slug);

CREATE TABLE IF NOT EXISTS guest_usage (
    id         INTEGER PRIMARY KEY,
    slug       TEXT NOT NULL,
    day        TEXT NOT NULL,
    visitor_id TEXT NOT NULL DEFAULT '',
    questions  INTEGER NOT NULL DEFAULT 0,
    tokens     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_guest_usage_key ON guest_usage(slug, day, visitor_id);
"""


def data_dir() -> str:
    from agent.guest.profile import DATA_DIR, guests_root

    return os.path.join(guests_root(), DATA_DIR)


def sessions_dir(slug: str) -> str:
    return os.path.join(data_dir(), "sessions", slug)


def _ensure_dir(path: str) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


# --- database ----------------------------------------------------------------

_ready_path: Optional[str] = None


def _db_path() -> str:
    return os.path.join(data_dir(), DB_FILE)


@contextmanager
def _db(write: bool = False) -> Iterator[sqlite3.Connection]:
    """A connection to guest.db; with ``write`` the block is one immediate
    transaction, so a read-then-write inside it cannot interleave."""
    global _ready_path
    path = _db_path()
    with _lock:
        fresh = _ready_path != path or not os.path.exists(path)
        if fresh:
            _ensure_dir(data_dir())
        conn = sqlite3.connect(path, timeout=10, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            if fresh:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                _ready_path = path
            conn.execute("PRAGMA synchronous=NORMAL")
            if not write:
                yield conn
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()


def _loads(text: str) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


# --- secret ------------------------------------------------------------------

_secret_cache: Optional[tuple] = None


def secret_key() -> bytes:
    global _secret_cache
    path = os.path.join(data_dir(), "secret.key")
    with _lock:
        if _secret_cache is not None and _secret_cache[0] == path and os.path.exists(path):
            return _secret_cache[1]
        try:
            with open(path, "rb") as f:
                key = f.read().strip()
            if len(key) >= 32:
                _secret_cache = (path, key)
                return key
        except OSError:
            pass
        _ensure_dir(data_dir())
        key = secrets.token_hex(32).encode()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        _secret_cache = (path, key)
        return key


# --- shares ------------------------------------------------------------------

_ENTRY_FIELDS = ("share_token", "password_hash", "epoch", "confirmed", "confirmed_at", "disabled", "created_at")


def _entry_of(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "share_token": row["share_token"],
        "password_hash": row["password_hash"],
        "epoch": int(row["epoch"] or 1),
        "confirmed": _loads(row["confirmed"]),
        "confirmed_at": row["confirmed_at"],
        "disabled": bool(row["disabled"]),
        "created_at": row["created_at"],
    }


def _share_row(conn: sqlite3.Connection, slug: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM guest_shares WHERE slug = ? ORDER BY id LIMIT 1", (slug,)).fetchone()


def get_entry(slug: str) -> Optional[Dict[str, Any]]:
    with _db() as conn:
        row = _share_row(conn, slug)
    return _entry_of(row) if row else None


def entries() -> Dict[str, Dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM guest_shares ORDER BY id").fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        out.setdefault(row["slug"], _entry_of(row))
    return out


def update_entry(slug: str, **changes) -> Dict[str, Any]:
    """Apply ``changes`` to a profile's entry, creating it if needed."""
    unknown = set(changes) - set(_ENTRY_FIELDS)
    if unknown:
        raise KeyError(", ".join(sorted(unknown)))
    now = time.time()
    with _db(write=True) as conn:
        row = _share_row(conn, slug)
        if row is None:
            entry = {
                "share_token": secrets.token_urlsafe(18),
                "password_hash": "",
                "epoch": 1,
                "confirmed": None,
                "confirmed_at": 0,
                "disabled": False,
                "created_at": now,
            }
        else:
            entry = _entry_of(row)
        entry.update(copy.deepcopy(changes))
        values = (
            entry["share_token"], entry["password_hash"], int(entry["epoch"] or 1),
            json.dumps(entry["confirmed"], ensure_ascii=False) if entry["confirmed"] is not None else "",
            float(entry["confirmed_at"] or 0), 1 if entry["disabled"] else 0, float(entry["created_at"] or now), now,
        )
        if row is None:
            conn.execute(
                "INSERT INTO guest_shares (share_token, password_hash, epoch, confirmed, confirmed_at, disabled,"
                " created_at, updated_at, slug) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values + (slug,),
            )
        else:
            conn.execute(
                "UPDATE guest_shares SET share_token = ?, password_hash = ?, epoch = ?, confirmed = ?,"
                " confirmed_at = ?, disabled = ?, created_at = ?, updated_at = ? WHERE id = ?", values + (row["id"],),
            )
    return entry


def purge(slug: str) -> None:
    """Forget a profile entirely: its link, conversations, usage and files."""
    with _db(write=True) as conn:
        for table in ("guest_shares", "guest_sessions", "guest_messages", "guest_usage"):
            conn.execute(f"DELETE FROM {table} WHERE slug = ?", (slug,))
    shutil.rmtree(sessions_dir(slug), ignore_errors=True)


def find_by_share_token(share_token: str) -> Optional[str]:
    if not share_token:
        return None
    with _db() as conn:
        rows = conn.execute("SELECT slug, share_token FROM guest_shares WHERE share_token = ? ORDER BY id",
                            (share_token,)).fetchall()
    for row in rows:
        if constant_time_equals(row["share_token"] or "", share_token):
            return row["slug"]
    return None


def confirm(slug: str, config: Dict[str, Any]) -> Dict[str, Any]:
    return update_entry(slug, confirmed=copy.deepcopy(config), confirmed_at=time.time())


def reset_link(slug: str) -> Dict[str, Any]:
    return update_entry(slug, share_token=secrets.token_urlsafe(18))


def revoke_sessions(slug: str) -> Dict[str, Any]:
    entry = get_entry(slug) or {}
    return update_entry(slug, epoch=int(entry.get("epoch") or 1) + 1)


# --- passwords ---------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8", "surrogatepass"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def set_password(slug: str, password: str) -> Dict[str, Any]:
    """Set (or clear, with an empty string) the access password. Either way
    every visitor token issued before stops working."""
    entry = get_entry(slug) or {}
    return update_entry(
        slug,
        password_hash=hash_password(password) if password else "",
        epoch=int(entry.get("epoch") or 1) + 1,
    )


# --- visitor tokens ----------------------------------------------------------


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _unb64(text: str) -> str:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode()


def _scope(entry: Dict[str, Any]) -> str:
    # The password hash and share token are part of what is signed, so
    # changing either retires every token issued against the old value.
    return "|".join([
        str(entry.get("epoch") or 1),
        entry.get("share_token") or "",
        entry.get("password_hash") or "",
    ])


def _sign(*parts: str) -> str:
    return hmac.new(secret_key(), "\n".join(parts).encode(), hashlib.sha256).hexdigest()


VISITOR_ID_LEN = 24


def new_visitor_id() -> str:
    return secrets.token_hex(VISITOR_ID_LEN // 2)


def new_session_id(visitor_id: str) -> str:
    return visitor_id + secrets.token_hex(6)


def owns_session(visitor_id: str, session_id: str) -> bool:
    return (
        isinstance(session_id, str)
        and len(session_id) == VISITOR_ID_LEN + 12
        and session_id.isalnum()
        and session_id.startswith(visitor_id)
    )


def visitor_of(session_id: str) -> str:
    return session_id[:VISITOR_ID_LEN]


def issue_token(slug: str, visitor_id: str) -> str:
    entry = get_entry(slug)
    if not entry:
        raise KeyError(slug)
    ts = format(int(time.time()), "x")
    sig = _sign("visitor", slug, visitor_id, ts, _scope(entry))
    return f"{_TOKEN_PREFIX}.{_b64(slug)}.{visitor_id}.{ts}.{sig}"


def verify_token(token: str, slug: str, ttl_seconds: int) -> Optional[str]:
    """The visitor id ``token`` was issued for, or None if it is not valid
    for ``slug`` right now."""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != _TOKEN_PREFIX:
        return None
    _, slug_b64, session_id, ts_hex, sig = parts
    try:
        if _unb64(slug_b64) != slug:
            return None
        ts = int(ts_hex, 16)
    except (ValueError, UnicodeDecodeError):
        return None
    if not session_id.isalnum() or len(session_id) != VISITOR_ID_LEN:
        return None
    if time.time() - ts > ttl_seconds:
        return None
    entry = get_entry(slug)
    if not entry:
        return None
    expected = _sign("visitor", slug, session_id, ts_hex, _scope(entry))
    if not constant_time_equals(sig, expected):
        return None
    return session_id


def sign_file(slug: str, session_id: str, vpath: str, expires: int) -> str:
    entry = get_entry(slug) or {}
    return _sign("file", slug, session_id, vpath, str(expires), _scope(entry))[:32]


def verify_file(slug: str, session_id: str, vpath: str, expires: int, sig: str) -> bool:
    if expires < time.time():
        return False
    return constant_time_equals(sig or "", sign_file(slug, session_id, vpath, expires))


# --- usage -------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


def _bump_usage(slug: str, visitor_id: str, questions: int = 0, tokens: int = 0) -> None:
    day = _today()
    try:
        with _db(write=True) as conn:
            row = conn.execute(
                "SELECT id FROM guest_usage WHERE slug = ? AND day = ? AND visitor_id = ? ORDER BY id LIMIT 1",
                (slug, day, visitor_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO guest_usage (slug, day, visitor_id, questions, tokens) VALUES (?, ?, ?, ?, ?)",
                    (slug, day, visitor_id, questions, tokens),
                )
            else:
                conn.execute(
                    "UPDATE guest_usage SET questions = questions + ?, tokens = tokens + ? WHERE id = ?",
                    (questions, tokens, row["id"]),
                )
    except sqlite3.Error as e:
        logger.warning(f"[GuestShare] Could not record usage: {e}")


def tokens_today(slug: str) -> int:
    with _db() as conn:
        row = conn.execute("SELECT COALESCE(SUM(tokens), 0) AS n FROM guest_usage WHERE slug = ? AND day = ?",
                           (slug, _today())).fetchone()
    return int(row["n"])


def questions_today(slug: str, visitor_id: str) -> int:
    with _db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(questions), 0) AS n FROM guest_usage WHERE slug = ? AND day = ? AND visitor_id = ?",
            (slug, _today(), visitor_id),
        ).fetchone()
    return int(row["n"])


def add_question(slug: str, visitor_id: str) -> int:
    _bump_usage(slug, visitor_id, questions=1)
    return questions_today(slug, visitor_id)


def add_tokens(slug: str, visitor_id: str, tokens: int) -> int:
    if tokens > 0:
        _bump_usage(slug, visitor_id, tokens=int(tokens))
    return tokens_today(slug)


# --- transcripts -------------------------------------------------------------

# Records with role "event" mark what happened to a conversation rather than
# what was said: "clear" starts a fresh context for the model, "deleted" hides
# the conversation from its visitor (the owner keeps it).
EVENT_CLEAR = "clear"
EVENT_DELETED = "deleted"

_TITLE_LEN = 60


def _one_line(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _session_row(conn: sqlite3.Connection, slug: str, session_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM guest_sessions WHERE session_id = ? AND slug = ? ORDER BY id LIMIT 1", (session_id, slug),
    ).fetchone()


def append_message(slug: str, session_id: str, record: Dict[str, Any]) -> None:
    """Add one transcript record; the first one also opens the conversation."""
    record = dict(record)
    ts = float(record.pop("ts", None) or time.time())
    role = str(record.pop("role", "") or "")
    content = str(record.pop("content", "") or "")
    tokens = int(record.pop("tokens", 0) or 0)
    extras = json.dumps(record, ensure_ascii=False) if record else ""
    asked = role == "user"
    with _db(write=True) as conn:
        conn.execute(
            "INSERT INTO guest_messages (slug, session_id, role, content, extras, tokens, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", (slug, session_id, role, content, extras, tokens, ts),
        )
        row = _session_row(conn, slug, session_id)
        if row is None:
            conn.execute(
                "INSERT INTO guest_sessions (slug, session_id, visitor_id, title, last_question, questions,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, session_id, visitor_of(session_id), _one_line(content, _TITLE_LEN) if asked else "",
                 _one_line(content, 200) if asked else "", 1 if asked else 0, ts, ts),
            )
        elif asked:
            conn.execute(
                "UPDATE guest_sessions SET questions = questions + 1, last_question = ?, updated_at = ?,"
                " title = CASE WHEN title = '' THEN ? ELSE title END WHERE id = ?",
                (_one_line(content, 200), ts, _one_line(content, _TITLE_LEN), row["id"]),
            )
        else:
            conn.execute("UPDATE guest_sessions SET updated_at = ? WHERE id = ?", (ts, row["id"]))


def _record_of(row: sqlite3.Row) -> Dict[str, Any]:
    record: Dict[str, Any] = _loads(row["extras"]) or {}
    record.update({"role": row["role"], "content": row["content"], "ts": row["created_at"]})
    if row["tokens"]:
        record["tokens"] = row["tokens"]
    return record


def read_messages(slug: str, session_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    """The last ``limit`` records of a conversation, oldest first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM guest_messages WHERE session_id = ? AND slug = ? ORDER BY id DESC LIMIT ?",
            (session_id, slug, int(limit)),
        ).fetchall()
    return [_record_of(row) for row in reversed(rows)]


def session_exists(slug: str, session_id: str) -> bool:
    with _db() as conn:
        return _session_row(conn, slug, session_id) is not None


def last_activity(slug: str, session_id: str) -> Optional[float]:
    with _db() as conn:
        row = _session_row(conn, slug, session_id)
    return row["updated_at"] if row else None


def is_deleted(slug: str, session_id: str) -> bool:
    with _db() as conn:
        row = _session_row(conn, slug, session_id)
    return bool(row and row["deleted_at"])


def mark_deleted(slug: str, session_id: str) -> bool:
    """Hide a conversation from its visitor; the owner keeps the transcript."""
    now = time.time()
    with _db(write=True) as conn:
        row = _session_row(conn, slug, session_id)
        if row is None or row["deleted_at"]:
            return False
        conn.execute("UPDATE guest_sessions SET deleted_at = ? WHERE id = ?", (now, row["id"]))
        conn.execute(
            "INSERT INTO guest_messages (slug, session_id, role, extras, created_at) VALUES (?, ?, 'event', ?, ?)",
            (slug, session_id, json.dumps({"event": EVENT_DELETED}), now),
        )
    return True


def visitor_sessions(slug: str, visitor_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """The visitor's own conversations, newest first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM guest_sessions"
            " WHERE slug = ? AND visitor_id = ? AND deleted_at = 0 AND questions > 0"
            " ORDER BY updated_at DESC LIMIT ?", (slug, visitor_id, int(limit)),
        ).fetchall()
    return [{"session_id": r["session_id"], "title": r["title"], "updated_at": r["updated_at"],
             "created_at": r["created_at"]} for r in rows if owns_session(visitor_id, r["session_id"])]


def list_sessions(slug: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Every conversation of a profile for its owner, newest first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT session_id, last_question, questions, created_at, updated_at, deleted_at FROM guest_sessions"
            " WHERE slug = ? ORDER BY updated_at DESC LIMIT ?", (slug, int(limit)),
        ).fetchall()
    return [{"session_id": r["session_id"], "last": r["last_question"][:120], "questions": r["questions"],
             "created_at": r["created_at"], "updated_at": r["updated_at"], "deleted": bool(r["deleted_at"])}
            for r in rows]
