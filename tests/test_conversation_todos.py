"""Durable, session-scoped todo snapshots and their transaction boundaries."""

import os
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory.conversation_store import ConversationStore


TODOS = [{"id": "one", "content": "Read 源码", "status": "in_progress"}]


def _session(store, sid="session", channel="web"):
    store.append_messages(sid, [{"role": "user", "content": "hello"}], channel_type=channel)


def _rows(path):
    with sqlite3.connect(str(path)) as conn:
        return conn.execute(
            "SELECT agent_id, session_id, version, todos_json FROM todo_snapshots "
            "ORDER BY agent_id, session_id, version"
        ).fetchall()


def test_snapshot_persists_and_empty_list_replaces(tmp_path):
    path = tmp_path / "index.db"
    store = ConversationStore(path)
    _session(store)
    assert store.get_todo_snapshot("session") is None
    assert store.commit_todo_snapshot("session", "run", "call", TODOS, "Started") == 1
    reopened = ConversationStore(path)
    snapshot = reopened.get_todo_snapshot("session")
    assert snapshot == {
        "version": 1, "run_id": "run", "tool_call_id": "call",
        "todos": TODOS, "explanation": "Started", "created_at": snapshot["created_at"],
    }
    assert isinstance(snapshot["created_at"], int) and snapshot["created_at"] > 0
    assert reopened.commit_todo_snapshot("session", "run", "clear", []) == 2
    assert ConversationStore(path).get_todo_snapshot("session")["todos"] == []
    assert len(_rows(path)) == 2


def test_agents_and_sessions_have_independent_versions(tmp_path):
    path = tmp_path / "index.db"
    first = ConversationStore(path, agent_id="first")
    second = ConversationStore(path, agent_id="second")
    _session(first)
    _session(second)
    _session(first, "other")
    assert first.commit_todo_snapshot("session", "run", "call", TODOS) == 1
    assert second.get_todo_snapshot("session") is None
    assert second.commit_todo_snapshot("session", "run", "call", []) == 1
    assert first.commit_todo_snapshot("other", "run", "call", []) == 1
    assert first.get_todo_snapshot("session")["todos"] == TODOS
    first.clear_session("session")
    assert second.get_todo_snapshot("session")["todos"] == []
    assert first.get_todo_snapshot("other")["version"] == 1


def test_retry_uses_canonical_payload_and_conflict_rolls_back(tmp_path):
    path = tmp_path / "index.db"
    store = ConversationStore(path)
    _session(store)
    assert store.commit_todo_snapshot("session", "run", "call", TODOS, "why") == 1
    reordered = [{"status": "in_progress", "content": "Read 源码", "id": "one"}]
    assert store.commit_todo_snapshot("session", "run", "call", reordered, "why") == 1
    for todos, explanation in (([], "why"), (TODOS, "changed")):
        with pytest.raises(ValueError, match="Conflicting"):
            store.commit_todo_snapshot("session", "run", "call", todos, explanation)
    assert len(_rows(path)) == 1
    assert store.commit_todo_snapshot("session", "run", "next", []) == 2
    # A delayed retry returns its original version, without replacing the latest.
    assert store.commit_todo_snapshot("session", "run", "call", TODOS, "why") == 1
    assert store.get_todo_snapshot("session")["version"] == 2


@pytest.mark.parametrize("same_call", [False, True])
def test_independent_stores_serialize_concurrent_commits(tmp_path, same_call):
    path = tmp_path / "index.db"
    stores = [ConversationStore(path) for _ in range(8)]
    _session(stores[0])
    barrier = threading.Barrier(len(stores))

    def commit(i):
        barrier.wait(timeout=10)
        return stores[i].commit_todo_snapshot(
            "session", "run", "same" if same_call else str(i), TODOS
        )

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        versions = list(pool.map(commit, range(len(stores))))
    expected = [1] * len(stores) if same_call else list(range(1, len(stores) + 1))
    assert sorted(versions) == expected
    assert len(_rows(path)) == (1 if same_call else len(stores))
    assert stores[0].get_todo_snapshot("session")["version"] == max(expected)


def test_missing_or_deleted_session_rejects_late_commit(tmp_path):
    path = tmp_path / "index.db"
    store = ConversationStore(path)
    with pytest.raises(ValueError, match="session does not exist"):
        store.commit_todo_snapshot("session", "run", "call", TODOS)
    assert store.list_session_ids() == []
    _session(store)
    store.commit_todo_snapshot("session", "run", "call", TODOS)
    store.clear_session("session")
    assert _rows(path) == []
    assert store.get_todo_snapshot("session") is None
    for call in ("call", "late"):
        with pytest.raises(ValueError, match="session does not exist"):
            store.commit_todo_snapshot("session", "run", call, TODOS)
    assert store.list_session_ids() == []


def test_retention_removes_todos_only_for_expired_agent_sessions(tmp_path):
    path = tmp_path / "index.db"
    store = ConversationStore(path, agent_id="first")
    other = ConversationStore(path, agent_id="second")
    for sid, channel in (("expired", "im"), ("permanent", "web"), ("recent", "im")):
        _session(store, sid, channel)
        store.commit_todo_snapshot(sid, "run", "call", TODOS)
    _session(other, "expired", "im")
    other.commit_todo_snapshot("expired", "run", "call", TODOS)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("UPDATE sessions SET last_active = 1 WHERE session_id != 'recent'")
    assert store.cleanup_old_sessions(max_age_days=1) == 1
    assert store.get_todo_snapshot("expired") is None
    assert store.get_todo_snapshot("permanent") is not None
    assert store.get_todo_snapshot("recent") is not None
    assert other.get_todo_snapshot("expired") is not None
    with pytest.raises(ValueError, match="session does not exist"):
        store.commit_todo_snapshot("expired", "run", "late", [])
    assert len(_rows(path)) == 3


def test_context_message_and_run_deletion_preserve_todos(tmp_path):
    store = ConversationStore(tmp_path / "index.db")
    _session(store)
    store.create_run("run", session_id="session")
    store.commit_todo_snapshot("session", "run", "call", TODOS)
    before = store.get_todo_snapshot("session")
    store.clear_context("session")
    assert store.get_todo_snapshot("session") == before
    assert store.delete_message_pair("session", 0) == 1
    assert store.get_todo_snapshot("session") == before
    assert store.delete_run("run") is True
    assert store.get_todo_snapshot("session") == before


def test_insert_failure_rolls_back_and_does_not_consume_version(tmp_path):
    path = tmp_path / "index.db"
    store = ConversationStore(path)
    _session(store)
    store.commit_todo_snapshot("session", "run", "first", TODOS)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TRIGGER reject_todos BEFORE INSERT ON todo_snapshots "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.commit_todo_snapshot("session", "run", "next", [])
    assert store.get_todo_snapshot("session")["version"] == 1
    assert len(_rows(path)) == 1
    with sqlite3.connect(str(path)) as conn:
        conn.execute("DROP TRIGGER reject_todos")
    assert store.commit_todo_snapshot("session", "run", "next", []) == 2


@pytest.mark.parametrize("retention", [False, True])
def test_session_deletion_failure_rolls_back_messages_and_todos(tmp_path, retention):
    path = tmp_path / "index.db"
    store = ConversationStore(path)
    _session(store, channel="im")
    store.commit_todo_snapshot("session", "run", "call", TODOS)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("UPDATE sessions SET last_active = 1")
        conn.execute(
            "CREATE TRIGGER reject_session_delete BEFORE DELETE ON sessions "
            "BEGIN SELECT RAISE(ABORT, 'injected deletion failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected deletion failure"):
        if retention:
            store.cleanup_old_sessions(max_age_days=1)
        else:
            store.clear_session("session")
    assert store.list_session_ids() == ["session"]
    assert store.load_messages("session") == [{"role": "user", "content": "hello"}]
    assert store.get_todo_snapshot("session")["todos"] == TODOS


def test_missing_snapshot_table_fails_closed(tmp_path):
    path = tmp_path / "index.db"
    store = ConversationStore(path)
    _session(store)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("DROP TABLE todo_snapshots")
    with pytest.raises(sqlite3.OperationalError, match="todo_snapshots"):
        store.commit_todo_snapshot("session", "run", "call", TODOS)
    assert store.list_session_ids() == ["session"]
