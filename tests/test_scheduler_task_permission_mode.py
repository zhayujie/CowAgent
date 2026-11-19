"""A scheduled Agent run must not be allowed more than the conversation that
created it.

Each run gets its own ``scheduler_*`` session with no permission override, so
without a mode of its own it fell back to the instance-wide default: a task
created from a ``workspace-write`` conversation ran with ``full-access``, and
pinning that conversation to ``read-only`` later did not reach its tasks.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.tools.scheduler.integration import (
    _execute_agent_task,
    _task_permission_mode,
)
from agent.tools.scheduler.scheduler_tool import SchedulerTool
from bridge.context import Context, ContextType


@pytest.fixture
def prefs(monkeypatch):
    """Session permission pins keyed by (session_id, agent_id); global full-access."""
    pins = {}

    def get_prefs(session_id, agent_id=None):
        mode = pins.get((session_id, agent_id))
        return {"permission": mode} if mode else {}

    monkeypatch.setattr("agent.workspace.session_prefs.get_prefs", get_prefs)
    monkeypatch.setattr("agent.permission.global_mode", lambda: "full-access")
    return pins


class _TaskStore:
    def __init__(self):
        self.tasks = []

    def add_task(self, task):
        self.tasks.append(task)


def _create_agent_task(session_id="chat-1", agent_id="a1", **context_values):
    context = Context(ContextType.TEXT, "hello")
    context["channel_type"] = "web"
    context["receiver"] = session_id
    context["session_id"] = session_id
    context["agent_id"] = agent_id
    context["isgroup"] = False
    for key, value in context_values.items():
        context[key] = value
    tool = SchedulerTool({"channel_type": "web"})
    tool.current_context = context
    tool.task_store = _TaskStore()
    result = tool._create_task(
        name="nightly",
        ai_task="clean up the build folder",
        schedule_type="interval",
        schedule_value="3600",
    )
    assert "错误" not in result, result
    return tool.task_store.tasks[0]


def _task(**action):
    return {"id": "t1", "agent_id": "a1", "action": {"type": "agent_task", **action}}


def test_creation_records_the_conversation_and_its_mode(prefs):
    prefs[("chat-1", "a1")] = "workspace-write"

    action = _create_agent_task()["action"]

    assert action["origin_session_id"] == "chat-1"
    assert action["origin_agent_id"] == "a1"
    assert action["permission_mode"] == "workspace-write"


def test_creation_in_a_delegated_turn_records_the_delegated_mode(prefs):
    action = _create_agent_task(delegated_permission_mode="read-only")["action"]

    assert action["permission_mode"] == "read-only"


def test_creating_a_task_does_not_escalate_past_the_conversation(prefs):
    prefs[("chat-1", "a1")] = "workspace-write"
    task = _create_agent_task()
    # Even if the conversation's pin is cleared afterwards, the run stays
    # within what the creating conversation was allowed.
    prefs.clear()

    assert _task_permission_mode(task, "a1") == "workspace-write"


def test_a_later_downgrade_of_the_conversation_reaches_the_task(prefs):
    task = _create_agent_task()
    assert task["action"]["permission_mode"] == "full-access"

    prefs[("chat-1", "a1")] = "read-only"

    assert _task_permission_mode(task, "a1") == "read-only"


def test_a_stricter_global_mode_still_applies(prefs, monkeypatch):
    task = _task(permission_mode="full-access", origin_session_id="chat-1", origin_agent_id="a1")
    monkeypatch.setattr("agent.permission.global_mode", lambda: "read-only")

    assert _task_permission_mode(task, "a1") == "read-only"


def test_a_conversation_pinned_wider_than_global_keeps_its_mode(prefs, monkeypatch):
    # Same rule as the chat itself: a session pin overrides the global default.
    monkeypatch.setattr("agent.permission.global_mode", lambda: "read-only")
    prefs[("chat-1", "a1")] = "workspace-write"
    task = _create_agent_task()

    assert _task_permission_mode(task, "a1") == "workspace-write"


def test_legacy_task_follows_the_conversation_it_delivers_to(prefs):
    prefs[("chat-1", "a1")] = "read-only"

    assert _task_permission_mode(_task(notify_session_id="chat-1"), "a1") == "read-only"
    assert _task_permission_mode(_task(notify_session_id="other"), "a1") == "full-access"


def test_agent_task_run_carries_the_mode_into_agent_reply(prefs):
    prefs[("chat-1", "a1")] = "read-only"
    calls = []

    class _Bridge:
        def agent_reply(self, query, context=None, **kwargs):
            calls.append(context)
            return SimpleNamespace(content="")

    task = _task(
        task_description="clean up the build folder",
        receiver="chat-1",
        channel_type="web",
        notify_session_id="chat-1",
        origin_session_id="chat-1",
        origin_agent_id="a1",
        permission_mode="full-access",
    )
    _execute_agent_task(task, _Bridge(), "a1")

    assert calls[0]["session_id"] == "scheduler_chat-1_t1"
    assert calls[0]["delegated_permission_mode"] == "read-only"


def test_console_edit_cannot_rewrite_the_recorded_mode(tmp_path, monkeypatch):
    from agent.tools.scheduler.task_store import TaskStore
    from channel.web.api import scheduler as scheduler_api

    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    store.add_task({
        "id": "t1",
        "name": "nightly",
        "enabled": True,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "next_run_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        "schedule": {"type": "interval", "seconds": 3600},
        "action": {
            "type": "agent_task",
            "task_description": "clean up",
            "receiver": "chat-1",
            "channel_type": "web",
            "notify_session_id": "chat-1",
            "origin_session_id": "chat-1",
            "origin_agent_id": "a1",
            "permission_mode": "read-only",
        },
    })
    payload = {
        "task_id": "t1",
        "action": {
            "type": "agent_task",
            "task_description": "clean up more",
            "receiver": "chat-1",
            "channel_type": "web",
            "origin_session_id": "elsewhere",
            "origin_agent_id": "a2",
            "permission_mode": "full-access",
        },
    }
    with patch("channel.web.api.scheduler._require_auth"), \
            patch("channel.web.api.scheduler.web.header"), \
            patch("channel.web.api.scheduler.web.data", return_value=json.dumps(payload).encode()), \
            patch("channel.web.api.scheduler._global_task_store", return_value=store):
        result = json.loads(scheduler_api.SchedulerUpdateHandler().POST())

    assert result["status"] == "success", result
    action = store.get_task("t1")["action"]
    assert action["task_description"] == "clean up more"
    assert action["origin_session_id"] == "chat-1"
    assert action["origin_agent_id"] == "a1"
    assert action["permission_mode"] == "read-only"
