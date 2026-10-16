"""Executor todo ownership, durable event ordering, and per-call isolation."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.memory.conversation_store import ConversationStore
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.todo_write.todo_write_tool import TodoContext, TodoWriteTool
from common.utils import clear_agent_run_id, set_agent_run_id


TODOS = [{"content": "Read source", "status": "in_progress"}]


class RecordingTodo(TodoWriteTool):
    def __init__(self):
        super().__init__()
        self.instances = []

    def execute(self, params):
        self.instances.append(self)
        return super().execute(params)


def _store(path, agent_id="owner", session_id="session"):
    store = ConversationStore(path, agent_id=agent_id)
    store.append_messages(session_id, [{"role": "user", "content": "hello"}])
    return store


def _executor(tool, events):
    # Use the same minimal executor surface as parallel/own-card tests, while
    # initializing the new ownership field through the production constructor.
    executor = AgentStreamExecutor(None, None, "", [tool])
    executor._emit_event = lambda kind, data: events.append((kind, data))
    return executor


def _call(executor, run_id="run", call_id="call", todos=None, override=None):
    token = set_agent_run_id(run_id)
    try:
        return executor._execute_tool({
            "id": call_id, "name": "todo_write",
            "arguments": {"todos": TODOS if todos is None else todos, "explanation": "Started"},
        }, tool_override=override)
    finally:
        clear_agent_run_id(token)


def _updates(events):
    return [data for kind, data in events if kind == "todo_update"]


def test_commit_is_durable_before_event_and_model_result(tmp_path):
    path = tmp_path / "index.db"
    store = _store(path)
    events = []
    executor = _executor(TodoWriteTool(), events)
    executor.bind_todo_owner(store, "session", "owner", "run")

    def emit(kind, data):
        if kind == "todo_update":
            snapshot = ConversationStore(path, agent_id="owner").get_todo_snapshot("session")
            assert snapshot["version"] == data["version"]
            assert snapshot["todos"] == data["todos"]
        events.append((kind, data))

    executor._emit_event = emit
    result = _call(executor)
    assert result["status"] == "success"
    assert json.loads(result["result"])["version"] == 1
    assert [kind for kind, _ in events] == ["tool_execution_start", "todo_update", "tool_execution_end"]
    assert _updates(events)[0] == {
        "agent_id": "owner", "session_id": "session", "run_id": "run",
        "tool_call_id": "call", "version": 1, "todos": TODOS,
        "counts": {"pending": 0, "in_progress": 1, "completed": 0}, "explanation": "Started",
    }


@pytest.mark.parametrize("failure", ["database", "validation", "cancelled", "deleted_session"])
def test_failure_preserves_snapshot_and_emits_no_update(tmp_path, failure):
    path = tmp_path / "index.db"
    store = _store(path)
    store.commit_todo_snapshot("session", "old", "old-call", TODOS)
    before = store.get_todo_snapshot("session")
    events = []
    tool = RecordingTodo()
    executor = _executor(tool, events)
    executor.bind_todo_owner(store, "session", "owner", "run")
    todos = []
    if failure == "database":
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TRIGGER reject_todos BEFORE INSERT ON todo_snapshots BEGIN SELECT RAISE(ABORT, 'injected'); END")
    elif failure == "validation":
        todos = [{"content": "bad", "status": "invalid"}]
    elif failure == "cancelled":
        executor.cancel_event = threading.Event()
        executor.cancel_event.set()
    else:
        store.clear_session("session")
        before = None
    assert _call(executor, todos=todos)["status"] == "error"
    assert _updates(events) == []
    assert store.get_todo_snapshot("session") == before
    assert tool.instances[0].todo_context is None
    assert tool.instances[0].context is None


@pytest.mark.parametrize("override", [False, True])
def test_context_is_private_and_cleaned_even_with_override(tmp_path, override):
    tool = RecordingTodo()
    sentinel = TodoContext("stale", "stale", "stale", "stale", lambda *args: 99)
    tool.todo_context = sentinel
    store = _store(tmp_path / "index.db")
    executor = _executor(tool, [])
    executor.bind_todo_owner(store, "session", "owner", "run")
    assert _call(executor, override=tool if override else None)["status"] == "success"
    private = tool.instances[0]
    assert private is not tool
    assert tool.todo_context is sentinel
    for attr in ("todo_context", "context", "cancel_event", "progress_callback", "event_callback", "tool_call_id"):
        assert getattr(private, attr) is None


@pytest.mark.parametrize("binding", ["missing", "missing_store", "missing_run", "wrong_run"])
def test_missing_or_mismatched_authority_fails_closed(tmp_path, binding):
    store = _store(tmp_path / "index.db")
    tool = RecordingTodo()
    # A shared tool's old context must never authorize an unbound child.
    tool.todo_context = TodoContext("owner", "session", "run", "old", lambda *args: 99)
    events = []
    executor = _executor(tool, events)
    if binding != "missing":
        executor.bind_todo_owner(None if binding == "missing_store" else store, "session", "owner", "run")
    run_id = None if binding == "missing_run" else "other" if binding == "wrong_run" else "run"
    assert _call(executor, run_id=run_id)["status"] == "error"
    assert store.get_todo_snapshot("session") is None
    assert not _updates(events)


def test_shared_tool_concurrent_owners_are_isolated(tmp_path):
    path = tmp_path / "index.db"
    owners = [("a", "session", "run-a"), ("b", "session", "run-b"), ("a", "other", "run-c")]
    tool = RecordingTodo()
    barrier = threading.Barrier(3)
    # Prepare schemas/sessions before racing calls; concurrent first-open WAL
    # migration is outside the executor ownership contract being tested.
    stores = [_store(path, agent_id, sid) for agent_id, sid, _ in owners]

    def execute(index):
        agent_id, sid, run_id = owners[index]
        store = stores[index]
        events = []
        executor = _executor(tool, events)
        executor.bind_todo_owner(store, sid, agent_id, run_id)
        barrier.wait(timeout=10)
        todos = [{"content": run_id, "status": "pending"}]
        assert _call(executor, run_id, todos=todos)["status"] == "success"
        assert store.get_todo_snapshot(sid)["todos"] == todos
        assert _updates(events)[0]["agent_id"] == agent_id
        assert _updates(events)[0]["session_id"] == sid
        assert _updates(events)[0]["run_id"] == run_id
        assert _updates(events)[0]["version"] == 1

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(execute, range(len(owners))))
    assert len({id(instance) for instance in tool.instances}) == 3
    assert tool.todo_context is None


def test_same_call_retry_is_idempotent_and_conflict_has_no_event(tmp_path):
    path = tmp_path / "index.db"
    store = _store(path)
    events = []
    executor = _executor(TodoWriteTool(), events)
    executor.bind_todo_owner(store, "session", "owner", "run")
    assert _call(executor)["status"] == "success"
    assert _call(executor)["status"] == "success"
    assert [event["version"] for event in _updates(events)] == [1, 1]
    events.clear()
    assert _call(executor, todos=[])["status"] == "error"
    assert _updates(events) == []
    assert store.get_todo_snapshot("session")["todos"] == TODOS
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM todo_snapshots").fetchone()[0] == 1
