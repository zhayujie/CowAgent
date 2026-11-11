# encoding: utf-8
"""The scheduler tool may only see and change its own Agent's tasks.

The task store is one global file: ``get_task_store`` ignores the agent_id it
is handed and its docstring says tasks are "filtered by ``agent_id`` at the
query, not by which store they live in". The Web console queries it that way
and creation stamps the owner, but the tool's list/get/delete/enable/disable
actions never looked at the owner -- so in a multi-Agent deployment any
conversation could list another Agent's reminders (name, schedule and
receiver included), read their message text, and disable or delete them: the
other side simply stops being reminded.
"""

import pytest

from agent.tools.scheduler.scheduler_tool import SchedulerTool
from agent.tools.scheduler.task_store import TaskStore


def _web_task(task_id, agent_id, name):
    """A minimal stored task in the shape ``add_task`` persists."""
    return {
        "id": task_id,
        "agent_id": agent_id,
        "enabled": True,
        "name": name,
        "schedule": {"type": "once", "value": "+5m"},
        "action": {
            "type": "send_message",
            "channel_type": "web",
            "receiver": "s1",
            "content": f"{name} body",
        },
        "created_at": "2026-10-24T00:00:00",
    }


def _tool(tmp_path, agent_id):
    """A tool running as *agent_id*, over a store owned by two Agents."""
    tool = SchedulerTool({"channel_type": "web", "agent_id": agent_id})
    tool.task_store = TaskStore(str(tmp_path / "tasks.json"))
    tool.task_store.add_task(_web_task("t-primary", "primary", "Primary reminder"))
    tool.task_store.add_task(_web_task("t-research", "research", "Research reminder"))
    return tool


def test_list_shows_only_the_calling_agents_tasks(tmp_path):
    tool = _tool(tmp_path, "primary")

    result = tool.execute({"action": "list"})

    assert result.status == "success", result.result
    assert "Primary reminder" in result.result
    assert "Research reminder" not in result.result


@pytest.mark.parametrize("action", ["get", "delete", "disable", "enable"])
def test_another_agents_task_is_not_reachable(tmp_path, action):
    tool = _tool(tmp_path, "primary")

    result = tool.execute({"action": action, "task_id": "t-research"})

    assert result.status == "error", result.result
    # Indistinguishable from a missing id: the caller learns nothing about a
    # roster it is not part of.
    assert "不存在" in result.result
    stored = tool.task_store.load_tasks()
    assert stored["t-research"]["enabled"] is True


def test_own_tasks_stay_reachable(tmp_path):
    tool = _tool(tmp_path, "primary")

    assert tool.execute({"action": "get", "task_id": "t-primary"}).status == "success"
    assert tool.execute({"action": "disable", "task_id": "t-primary"}).status == "success"
    assert tool.task_store.load_tasks()["t-primary"]["enabled"] is False
    assert tool.execute({"action": "enable", "task_id": "t-primary"}).status == "success"
    assert tool.execute({"action": "delete", "task_id": "t-primary"}).status == "success"
    assert "t-primary" not in tool.task_store.load_tasks()


def test_without_an_agent_id_the_tool_keeps_its_unscoped_behaviour(tmp_path):
    # A bare tool (CLI, unit tests) carries no identity; the fallback keeps
    # the whole store visible rather than hiding everything from everyone.
    tool = _tool(tmp_path, "")

    result = tool.execute({"action": "list"})

    assert result.status == "success", result.result
    assert "Primary reminder" in result.result
    assert "Research reminder" in result.result
