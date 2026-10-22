"""A non-default Agent's artifacts have to survive a page reload.

Live SSE builds the artifact cards without a root check
(``channel/web/core/channel.py`` -> ``_build_artifact_payload``), so a file an
Agent wrote shows up and auto-opens while its turn streams. ``/api/history`` has
no stream to fall back on: it rebuilds the cards from the stored steps, and the
workspace-internal filter it applies there needs the *session's* root. Resolving
that root for the default Agent instead makes a file the Agent wrote look like it
lives outside the workspace, so no card is emitted and the artifact silently
disappears on every reload -- with no error anywhere.

The neighbouring media rewrite in the same handler already resolves the root with
the request's ``agent_id``; this is the one call that dropped it.
"""

import json
import os
import sys
import types
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub

SESSION_ID = "s1"


@pytest.fixture
def two_agent_registry(tmp_path):
    """A default and a non-default Agent, each in its own workspace.

    Distinct dirs are the whole point: with both Agents sharing one root the
    bug under test cannot show, because every path would pass the filter.
    """
    from agent.memory import (
        clear_conversation_store_cache,
        reset_memory_configs,
    )
    from agent.registry import AgentProfile, AgentRegistry, set_agent_registry

    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("writer", "Writer", str(tmp_path / "writer")),
        ],
        default_agent_id="primary",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    reset_memory_configs()
    try:
        yield registry
    finally:
        reset_memory_configs()
        clear_conversation_store_cache()
        # ``None``, not the instance from before the test: set_agent_registry
        # pins process-wide, so restoring that instance would leave the
        # registry pinned and outlive this test.
        set_agent_registry(None)


def _write_step(path):
    return {
        "type": "tool",
        "id": "call-1",
        "name": "write",
        "arguments": {"path": str(path)},
        "result": "written",
        "is_error": False,
    }


def _history_for(agent_id, steps, page=1, snapshot=None):
    """The /api/history response for one assistant turn carrying ``steps``."""
    from channel.web.api import sessions as sessions_api

    class _Store:
        def get_todo_snapshot(self, session_id):
            assert session_id == SESSION_ID
            assert page == 1, 'older pages must not read snapshots'
            return snapshot

        def load_history_page(self, **kwargs):
            return {
                "messages": [
                    {"role": "assistant", "content": "wrote it", "steps": steps},
                ],
                "total": 1,
                "page": page,
                "page_size": 20,
                "has_more": False,
            }

    params = types.SimpleNamespace(
        session_id=SESSION_ID, page=str(page), page_size="20", agent_id=agent_id,
        until_seq="",
    )

    class _NoLiveStream:
        """No turn is in flight, so the handler skips the resumable-stream join."""

        def resumable_stream(self, session_id, agent_id=None):
            return None

    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api.web, "header", lambda *a, **k: None), \
         patch.object(sessions_api.web, "input", lambda **kwargs: params), \
         patch.object(sessions_api, "WebChannel", _NoLiveStream), \
         patch("agent.memory.get_conversation_store", lambda *a, **k: _Store()), \
         patch("agent.workspace.project_store.get_project_dir", return_value=None):
        return json.loads(sessions_api.HistoryHandler().GET())


def test_history_keeps_a_non_default_agents_artifact_across_a_reload(
    two_agent_registry, tmp_path
):
    """The regression: the root was resolved for the default Agent, so the file
    the "writer" Agent produced was filtered out and its card was never sent."""
    writer_workspace = tmp_path / "writer"
    writer_workspace.mkdir(parents=True, exist_ok=True)
    report = writer_workspace / "report.md"
    report.write_text("# Findings\n", encoding="utf-8")

    response = _history_for("writer", [_write_step(report)])

    assert response["status"] == "success"
    artifacts = response["messages"][0].get("artifacts")
    assert [a["file_name"] for a in artifacts or []] == ["report.md"]
    assert artifacts[0]["abs_path"] == str(report)


def test_history_still_reports_the_default_agents_artifact(
    two_agent_registry, tmp_path
):
    """The fix scopes the root, it does not change what counts as an artifact:
    the default Agent's own file keeps coming through."""
    primary_workspace = tmp_path / "primary"
    primary_workspace.mkdir(parents=True, exist_ok=True)
    note = primary_workspace / "note.md"
    note.write_text("hi", encoding="utf-8")

    response = _history_for("primary", [_write_step(note)])

    artifacts = response["messages"][0].get("artifacts")
    assert [a["file_name"] for a in artifacts or []] == ["note.md"]


def test_history_still_leaves_out_a_file_outside_the_sessions_root(
    two_agent_registry, tmp_path
):
    """Passing the Agent's own root must not widen the filter: a file outside it
    is still not a user-facing output of that Agent's workspace."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(parents=True, exist_ok=True)
    stray = elsewhere / "stray.md"
    stray.write_text("not mine", encoding="utf-8")

    response = _history_for("writer", [_write_step(stray)])

    assert response["messages"][0].get("artifacts") is None


@pytest.mark.parametrize("agent_id, expected_owner", [("writer", "writer"), ("", "primary")])
def test_history_first_page_includes_scoped_todo_snapshot(
    two_agent_registry, agent_id, expected_owner
):
    snapshot = {
        "version": 3,
        "todos": [{"content": "Check history", "status": "in_progress"}],
        "run_id": "run-1",
        "tool_call_id": "todo-1",
    }

    response = _history_for(agent_id, [], snapshot=snapshot)

    assert response["status"] == "success"
    assert response["agent_id"] == expected_owner
    assert response["session_id"] == SESSION_ID
    assert response["todo_snapshot"] == {
        **snapshot, "agent_id": expected_owner, "session_id": SESSION_ID,
    }
    assert "agent_id" not in snapshot  # Handler must not mutate the stored state.


def test_history_first_page_without_todos_returns_scoped_null(two_agent_registry):
    response = _history_for("writer", [])

    assert response["status"] == "success"
    assert response["agent_id"] == "writer"
    assert response["session_id"] == SESSION_ID
    assert "todo_snapshot" in response
    assert response["todo_snapshot"] is None


def test_history_older_pages_neither_read_nor_return_todo_snapshot(two_agent_registry):
    # The fixture's get_todo_snapshot raises if the handler reads it on page 2.
    response = _history_for("writer", [], page=2, snapshot={"version": 5, "todos": []})

    assert response["status"] == "success"
    assert response["page"] == 2
    assert "todo_snapshot" not in response
    assert "agent_id" not in response
    assert "session_id" not in response
