# encoding:utf-8
"""A conversation managing its background tasks through the task tool."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.task import overview
from agent.task import store as st


@pytest.fixture
def store(tmp_path):
    instance = st.TaskStore(str(tmp_path / "tasks.db"))
    with patch.object(st, "_store", instance):
        yield instance


@pytest.fixture
def enabled():
    with patch("config.conf", return_value={"task": {"enabled": True, "approval_rules": []}}):
        yield


_FEISHU = {"channel_type": "feishu", "receiver": "u1", "session_id": "u1"}
_OTHER = {"channel_type": "feishu", "receiver": "u2", "session_id": "u2"}
_WEB = {"channel_type": "web", "receiver": "s1", "session_id": "s1"}


def _chat_task(store, title, origin=_FEISHU, source=st.SOURCE_CHAT, **fields):
    task = store.create_task(title, "p", source=source, origin=dict(origin))
    if fields:
        store.update_task(task["id"], **fields)
    return store.get_task(task["id"])


# --- which tasks a conversation sees ------------------------------------------------

def test_list_shows_only_this_conversations_tasks(store, enabled):
    now = time.time()
    running = _chat_task(store, "周报", status=st.RUNNING, started_at=now - 180)
    _chat_task(store, "别人的", origin=_OTHER, status=st.RUNNING, started_at=now)
    _chat_task(store, "很久以前", status=st.DONE, finished_at=now - overview.RECENT_SECONDS - 60)
    _chat_task(store, "每日简报", source=st.SOURCE_SCHEDULE, status=st.DONE, finished_at=now)
    failed = _chat_task(store, "日报", source=st.SOURCE_SCHEDULE, status=st.FAILED,
                        finished_at=now, error="quota exceeded")

    listed = _tool(dict(_FEISHU)).execute({"action": "list"}).result
    assert f"#{running['id']}「周报」" in listed and "3" in listed
    assert f"#{failed['id']}「日报」" in listed and "quota exceeded" in listed
    assert "别人的" not in listed and "很久以前" not in listed and "每日简报" not in listed


def test_list_says_so_when_there_are_none(store, enabled):
    _chat_task(store, "别人的", origin=_OTHER, status=st.RUNNING, started_at=time.time())
    result = _tool(dict(_FEISHU)).execute({"action": "list"})
    assert result.status == "success" and "#" not in result.result


# --- the task tool -----------------------------------------------------------------

def _tool(context):
    from agent.tools.task.task import TaskTool

    tool = TaskTool()
    tool.context = SimpleNamespace(_current_context=context)
    return tool


def test_list_and_get_own_tasks(store, enabled):
    task = _chat_task(store, "周报", status=st.WAITING, wait_type=st.WAIT_APPROVAL,
                      started_at=time.time() - 60)
    store.create_approval(st.KIND_ACTION, task_id=task["id"], tool_name="bash",
                          summary="bash  git push origin main")
    tool = _tool(dict(_FEISHU))

    listed = tool.execute({"action": "list"})
    assert listed.status == "success" and f"#{task['id']}「周报」" in listed.result

    steps = [{"role": "assistant", "content": [
        {"type": "text", "text": "先汇总 issue"},
        {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "gh issue list"}},
    ]}]
    conv_store = MagicMock()
    conv_store.load_messages.return_value = steps
    bridge = MagicMock()
    bridge.get_conversation_store.return_value = conv_store
    with patch("agent.task.runner._get_bridge", return_value=bridge):
        detail = tool.execute({"action": "get", "task_id": f"#{task['id']}"})
    assert detail.status == "success"
    assert "git push origin main" in detail.result
    assert "先汇总 issue" in detail.result and "gh issue list" in detail.result
    conv_store.load_messages.assert_called_once_with(task["session_id"], max_turns=2)


def test_other_conversations_tasks_stay_out_of_reach(store, enabled):
    other = _chat_task(store, "别人的", origin=_OTHER, status=st.DONE, result="secret")
    tool = _tool(dict(_FEISHU))
    for action in ("get", "follow", "cancel", "delete"):
        refused = tool.execute({"action": action, "task_id": other["id"], "message": "x"})
        assert refused.status == "error" and "secret" not in str(refused.result)
    assert store.get_task(other["id"])["status"] == st.DONE

    shown = _tool(dict(_WEB)).execute({"action": "get", "task_id": other["id"]})
    assert shown.status == "success" and "secret" in shown.result


def test_follow_reopens_a_finished_task(store, enabled):
    task = _chat_task(store, "周报", status=st.DONE, result="r", finished_at=time.time())
    with patch("agent.task.runner.wake_runner"):
        result = _tool(dict(_FEISHU)).execute(
            {"action": "follow", "task_id": task["id"], "message": "加个图表"})
    assert result.status == "success" and f"#{task['id']}" in result.result
    task = store.get_task(task["id"])
    assert task["status"] == st.QUEUED and "加个图表" in task["pending_input"]


def test_follow_refuses_a_scheduled_run(store, enabled):
    task = _chat_task(store, "日报", source=st.SOURCE_SCHEDULE, status=st.DONE, result="r")
    result = _tool(dict(_FEISHU)).execute({"action": "follow", "task_id": task["id"], "message": "改一下"})
    assert result.status == "error"
    assert store.get_task(task["id"])["pending_input"] == ""


def test_cancel_and_delete(store, enabled):
    task = _chat_task(store, "周报", status=st.RUNNING, started_at=time.time())
    tool = _tool(dict(_FEISHU))
    runner = MagicMock()
    with patch("agent.task.runner.get_runner", return_value=runner):
        assert tool.execute({"action": "cancel", "task_id": task["id"]}).status == "success"
    assert store.get_task(task["id"])["status"] == st.CANCELLED
    runner.cancel.assert_called_once_with(task["id"])

    again = tool.execute({"action": "cancel", "task_id": task["id"]})
    assert again.status == "success" and ("已经结束" in again.result or "already" in again.result)

    with patch("agent.task.runner._clear_task_session"):
        assert tool.execute({"action": "delete", "task_id": task["id"]}).status == "success"
    assert store.get_task(task["id"]) is None


def test_background_runs_cannot_manage_tasks(store, enabled):
    task = _chat_task(store, "周报", status=st.RUNNING, started_at=time.time())
    result = _tool({**_FEISHU, "is_task": True}).execute({"action": "cancel", "task_id": task["id"]})
    assert result.status == "error"
    assert store.get_task(task["id"])["status"] == st.RUNNING


def test_chat_create_switch_only_takes_create_away(store):
    tool = _tool(dict(_FEISHU))
    with patch("config.conf", return_value={"task": {"enabled": True}}):
        assert "create" in tool.params["properties"]["action"]["enum"]
        assert "- create" in tool.description
    off = {"task": {"enabled": True, "chat_create": False}}
    with patch("config.conf", return_value=off):
        assert tool.is_available()
        assert tool.params["properties"]["action"]["enum"] == ["list", "get", "follow", "cancel", "delete"]
        assert "prompt" not in tool.params["properties"]
        assert "- create" not in tool.description
        refused = tool.execute({"action": "create", "title": "t", "prompt": "p"})
        assert refused.status == "error" and store.list_tasks() == []
        task = _chat_task(store, "周报", status=st.RUNNING, started_at=time.time())
        assert tool.execute({"action": "get", "task_id": task["id"]}).status == "success"


def test_first_creations_say_how_to_undo(store, enabled):
    from agent.tools.task import task as task_mod

    tool = _tool(dict(_FEISHU))
    tool.context.messages, tool.context.messages_lock, tool.context._current_agent_id = [], MagicMock(), ""
    results = []
    with patch("agent.task.runner.wake_runner"):
        for _ in range(task_mod.CREATE_HINT_LIMIT + 1):
            results.append(tool.execute({"action": "create", "title": "周报", "prompt": "p"}).result)
    hint = task_mod.CREATE_HINT_ZH
    assert all(hint in r or task_mod.CREATE_HINT_EN in r for r in results[:-1])
    assert hint not in results[-1] and task_mod.CREATE_HINT_EN not in results[-1]


def test_bad_calls_are_refused(store, enabled):
    tool = _tool(dict(_FEISHU))
    assert tool.execute({"action": "nope"}).status == "error"
    assert tool.execute({"action": "get"}).status == "error"
    assert tool.execute({"action": "create", "title": "t"}).status == "error"
