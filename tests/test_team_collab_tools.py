"""Tests for the team collaboration tools: team_send, team_inbox, team_task.

Each test runs against a real ``TeamStore`` in a throwaway directory, a real
``AgentRegistry``, and a fake bridge that records wake turns instead of
running them. Rosters come from a stubbed ``session_prefs.get_prefs``, the
same shape the real team conversation produces.
"""

import threading
import time

import pytest

from agent.registry import AgentProfile, AgentRegistry
from agent.team_runtime import CollabPolicy, TeamStore
from agent.tools.team_collab import _shared
from agent.tools.team_collab.team_inbox import TeamInboxTool
from agent.tools.team_collab.team_send import TeamSendTool
from agent.tools.team_collab.team_task import TeamTaskTool
from bridge.context import Context, ContextType


def _registry():
    return AgentRegistry(
        [
            AgentProfile("host", "Host", "/tmp/cow-host"),
            AgentProfile("mate", "Mate", "/tmp/cow-mate"),
        ],
        "host",
    )


def _context(agent_id="host", session_id="team1", **values):
    context = Context(ContextType.TEXT, "user turn", kwargs={})
    context["agent_id"] = agent_id
    context["session_id"] = session_id
    for key, value in values.items():
        context[key] = value
    return context


class FakeBridge:
    """Records wake turns instead of running them."""

    def __init__(self, registry=None):
        self.agent_registry = registry or _registry()
        self.calls = []
        self.seen = threading.Event()

    def agent_reply(self, query, context=None, on_event=None):
        self.calls.append((query, context, on_event))
        self.seen.set()


def _attach(tool, store, monkeypatch, policy=None, registry=None, **ctx_values):
    monkeypatch.setattr(_shared, "get_team_store", lambda: store)
    monkeypatch.setattr(
        _shared.TeamCollabContext,
        "policy",
        property(lambda self: policy or CollabPolicy()),
    )
    bridge = FakeBridge(registry or _registry())
    context = _context(**ctx_values)
    _shared.attach_team_collab_tools(tool, bridge, context)
    return tool, bridge


@pytest.fixture(autouse=True)
def _team_members(monkeypatch):
    """Every conversation is the team of host + mate."""
    from agent.workspace import session_prefs

    monkeypatch.setattr(
        session_prefs,
        "get_prefs",
        lambda session_id, agent_id=None: {"members": ["host", "mate"]},
    )


# -- team_send ---------------------------------------------------------------


def test_send_requires_attached_turn():
    tool = TeamSendTool()
    result = tool.execute({"to": "mate", "message": "hi"})
    assert result.status == "error"
    assert "not attached" in str(result.result)


def test_send_unknown_recipient_names_the_team(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamSendTool(), store, monkeypatch)
    result = tool.execute({"to": "ghost", "message": "hi"})
    assert result.status == "error"
    assert "Mate" in str(result.result)
    assert store.list_messages("team1") == []


def test_send_rejects_messaging_yourself(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamSendTool(), store, monkeypatch)
    result = tool.execute({"to": "Host", "message": "note to self"})
    assert result.status == "error"
    assert store.list_messages("team1") == []


def test_send_respects_max_message_chars(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    policy = CollabPolicy(max_message_chars=10)
    tool, _ = _attach(TeamSendTool(), store, monkeypatch, policy=policy)
    result = tool.execute({"to": "mate", "message": "0123456789abcdef"})
    assert result.status == "error"
    assert "10" in str(result.result)
    assert store.list_messages("team1") == []


def test_send_empty_message_fails(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamSendTool(), store, monkeypatch)
    assert tool.execute({"to": "mate", "message": "   "}).status == "error"


def test_send_delivers_and_wakes(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, bridge = _attach(TeamSendTool(), store, monkeypatch)
    result = tool.execute(
        {"to": "mate", "message": "please check the build", "type": "question"}
    )
    assert result.status == "success"
    payload = result.result
    assert payload["sent_to"][0]["id"] == "mate"
    assert payload["woken"] == ["mate"]

    record = store.list_messages("team1", to_id="mate")[0]
    assert record["msg_type"] == "question"
    assert record["content"] == "please check the build"
    assert record["read"] is False
    assert record["summary"] == "please check the build"

    assert bridge.seen.wait(5)
    query, wake_context, _ = bridge.calls[0]
    assert "please check the build" in query
    assert wake_context["delegation_root_session"] == "team1"
    assert wake_context["delegated_by"] == "host"
    assert wake_context["team_wake_depth"] == 1
    assert wake_context["is_delegated_task"] is True
    assert wake_context["session_id"].startswith("team_")

    feed = store.get_activity("team1")["items"]
    assert feed and feed[0]["kind"] == "message"
    assert feed[0]["actor"] == "host"


def test_send_broadcast_reaches_everyone_but_the_sender(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, bridge = _attach(TeamSendTool(), store, monkeypatch)
    result = tool.execute({"to": "all", "message": "standup in five"})
    assert result.status == "success"
    assert [entry["id"] for entry in result.result["sent_to"]] == ["mate"]
    assert store.unread_count("team1", "mate") == 1
    assert store.unread_count("team1", "host") == 0
    assert bridge.seen.wait(5)
    assert len(bridge.calls) == 1


def test_send_wake_disabled_notes_it(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    policy = CollabPolicy(wake_on_message=False)
    tool, bridge = _attach(TeamSendTool(), store, monkeypatch, policy=policy)
    result = tool.execute({"to": "mate", "message": "hi"})
    assert result.status == "success"
    assert result.result["woken"] == []
    assert result.result["sent_to"][0]["id"] == "mate"
    assert bridge.calls == []
    assert "waking disabled" in result.result["wake_note"]


def test_send_wake_depth_cap(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    policy = CollabPolicy(max_wake_depth=2)
    tool, bridge = _attach(
        TeamSendTool(), store, monkeypatch, policy=policy, team_wake_depth=2
    )
    result = tool.execute({"to": "mate", "message": "hi"})
    assert result.status == "success"
    assert result.result["woken"] == []
    assert bridge.calls == []
    assert "max depth" in result.result["wake_note"]


# -- team_inbox --------------------------------------------------------------

def _seed_inbox(store, count=2):
    for index in range(count):
        store.post_message(
            "team1",
            sender_id="host",
            sender_name="Host",
            recipients=[{"id": "mate", "name": "Mate"}],
            content=f"message {index}",
            msg_type="question" if index == 0 else "info",
        )
        time.sleep(0.01)  # distinct ts so newest-first ordering is deterministic


def test_inbox_lists_then_marks_read(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamInboxTool(), store, monkeypatch, agent_id="mate")
    _seed_inbox(store)

    listed = tool.execute({"action": "list"})
    assert listed.status == "success"
    payload = listed.result
    assert payload["count"] == 2
    assert payload["unread_before"] == 2
    assert payload["messages"][0]["content"] == "message 1"  # newest first
    assert payload["messages"][0]["msg_type"] == "info"
    assert payload["unread_remaining"] == 2

    ids = [m["id"] for m in payload["messages"]]
    marked = tool.execute({"action": "mark_read", "message_ids": ids})
    assert marked.status == "success"
    assert marked.result["marked_read"] == 2
    assert marked.result["unread_remaining"] == 0

    empty = tool.execute({"action": "list"})
    assert empty.result["count"] == 0
    assert empty.result["messages"] == []
    assert empty.result["unread_remaining"] == 0
    assert "empty" in str(empty.display)


def test_inbox_read_action_lists_and_marks(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamInboxTool(), store, monkeypatch, agent_id="mate")
    _seed_inbox(store, count=1)
    result = tool.execute({"action": "read"})
    assert result.status == "success"
    assert result.result["count"] == 1
    assert result.result["messages"][0]["content"] == "message 0"
    assert result.result["marked_read"] == 1
    assert result.result["unread_remaining"] == 0
    assert tool.execute({"action": "list"}).result["count"] == 0


def test_inbox_read_marks_only_the_given_ids(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamInboxTool(), store, monkeypatch, agent_id="mate")
    _seed_inbox(store)
    listed = tool.execute({"action": "list"}).result["messages"]
    target = listed[1]["id"]  # the older message

    result = tool.execute({"action": "read", "message_ids": [target]})
    assert result.status == "success"
    assert result.result["count"] == 1
    assert result.result["messages"][0]["id"] == target
    assert result.result["marked_read"] == 1
    assert result.result["unread_remaining"] == 1

    still_unread = tool.execute({"action": "list"}).result["messages"]
    assert len(still_unread) == 1
    assert still_unread[0]["content"] == "message 1"


def test_inbox_mark_read_needs_ids(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamInboxTool(), store, monkeypatch, agent_id="mate")
    assert tool.execute({"action": "mark_read"}).status == "error"


def test_inbox_unknown_action_fails(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamInboxTool(), store, monkeypatch, agent_id="mate")
    assert tool.execute({"action": "purge"}).status == "error"


# -- team_task ---------------------------------------------------------------


def test_task_create_claim_complete(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch, agent_id="mate")

    created = tool.execute({"action": "create", "subject": "Ship the release"})
    assert created.status == "success"
    task = created.result["task"]
    assert task["status"] == "pending"
    assert task["owner"] == ""  # unowned: up for grabs

    claimed = tool.execute({"action": "claim", "task_id": task["id"]})
    assert claimed.status == "success"
    claimed_task = claimed.result["task"]
    assert claimed_task["owner"] == "mate"
    assert claimed_task["status"] == "in_progress"

    done = tool.execute({"action": "complete", "task_id": task["id"]})
    assert done.status == "success"
    assert done.result["task"]["status"] == "completed"

    board = tool.execute({"action": "list"})
    assert board.result["count"] == 1
    assert board.result["tasks"][0]["status"] == "completed"

    feed = store.get_activity("team1")["items"]
    assert {entry["kind"] for entry in feed} == {"task"}


def test_task_unknown_id_fails(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch)
    assert tool.execute({"action": "get", "task_id": "nope"}).status == "error"


def test_task_owner_resolution(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch)

    created = tool.execute({"action": "create", "subject": "A", "owner": "me"})
    assert created.result["task"]["owner"] == "host"
    assert created.result["task"]["owner_name"] == "Host"

    assigned = tool.execute({"action": "create", "subject": "B", "owner": "Mate"})
    assert assigned.result["task"]["owner"] == "mate"

    bad = tool.execute({"action": "create", "subject": "C", "owner": "ghost"})
    assert bad.status == "error"
    assert "Host" in str(bad.result)  # the roster hint names who exists


def test_task_rejects_unknown_status(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch)
    task_id = tool.execute({"action": "create", "subject": "A"}).result["task"]["id"]
    result = tool.execute({"action": "update", "task_id": task_id, "status": "done"})
    assert result.status == "error"
    assert "in_progress" in str(result.result)


def test_task_blockers_gate_and_unblock(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch)
    first = tool.execute({"action": "create", "subject": "A"}).result["task"]
    second = tool.execute(
        {"action": "create", "subject": "B", "blocked_by": [first["id"]]}
    ).result["task"]
    assert second["blocked_by"] == [first["id"]]
    assert store.is_blocked("team1", second) is True

    done = tool.execute({"action": "complete", "task_id": first["id"]})
    assert done.status == "success"
    updated = store.get_task("team1", second["id"])
    assert store.is_blocked("team1", updated) is False


def test_task_self_block_is_dropped_not_an_error(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch)
    task_id = tool.execute({"action": "create", "subject": "A"}).result["task"]["id"]
    result = tool.execute({"action": "update", "task_id": task_id, "blocked_by": [task_id]})
    assert result.status == "success"
    assert result.result["task"]["blocked_by"] == []


def test_task_dependency_cycle_is_rejected(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch)
    first = tool.execute({"action": "create", "subject": "A"}).result["task"]
    second = tool.execute(
        {"action": "create", "subject": "B", "blocked_by": [first["id"]]}
    ).result["task"]
    result = tool.execute(
        {"action": "update", "task_id": first["id"], "blocked_by": [second["id"]]}
    )
    assert result.status == "error"
    assert "cycle" in str(result.result)


def test_task_unknown_action_fails(monkeypatch, tmp_path):
    store = TeamStore(root=tmp_path / "teams")
    tool, _ = _attach(TeamTaskTool(), store, monkeypatch)
    assert tool.execute({"action": "explode"}).status == "error"