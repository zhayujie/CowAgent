from copy import deepcopy

from channel.feishu.feishu_scheduler_card import (
    build_scheduler_card,
    handle_scheduler_action,
    tasks_for_receivers,
)


class FakeTaskStore:
    def __init__(self, tasks):
        self.tasks = {task["id"]: deepcopy(task) for task in tasks}
        self.enable_calls = []
        self.delete_calls = []

    def list_tasks(self):
        return list(self.tasks.values())

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def enable_task(self, task_id, enabled=True):
        self.enable_calls.append((task_id, enabled))
        self.tasks[task_id]["enabled"] = enabled

    def delete_task(self, task_id):
        self.delete_calls.append(task_id)
        del self.tasks[task_id]


def _task(task_id, receiver, enabled=True):
    return {
        "id": task_id,
        "name": "Daily report",
        "enabled": enabled,
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "next_run_at": "2026-07-18T09:00:00",
        "action": {"receiver": receiver, "channel_type": "feishu"},
    }


def test_scheduler_card_has_explicit_idempotent_actions():
    card = build_scheduler_card([_task("task-1", "chat-1")])

    assert card["schema"] == "2.0"
    assert card["config"]["enable_forward_interaction"] is False
    assert card["header"]["title"]["content"] == "Scheduled tasks"
    action_row = next(
        element for element in card["body"]["elements"] if element.get("tag") == "column_set"
    )
    values = [column["elements"][0]["value"] for column in action_row["columns"]]
    assert values == [
        {
            "cowagent": "scheduler",
            "action": "disable",
            "task_id": "task-1",
            "receiver": "chat-1",
        },
        {
            "cowagent": "scheduler",
            "action": "delete",
            "task_id": "task-1",
            "receiver": "chat-1",
        },
    ]


def test_scheduler_card_preserves_agent_owner_in_actions():
    card = build_scheduler_card(
        [_task("task-1", "chat-1")], agent_id="research"
    )
    action_row = next(
        element
        for element in card["body"]["elements"]
        if element.get("tag") == "column_set"
    )
    values = [column["elements"][0]["value"] for column in action_row["columns"]]
    assert {value["agent_id"] for value in values} == {"research"}


def test_tasks_are_scoped_to_callback_chat_or_operator():
    tasks = [
        _task("group", "chat-1"),
        _task("private", "user-1"),
        _task("other", "chat-2"),
    ]

    visible = tasks_for_receivers(tasks, {"chat-1", "user-1"})

    assert [task["id"] for task in visible] == ["group", "private"]


def test_disable_action_is_idempotent_and_returns_refreshed_card():
    store = FakeTaskStore([_task("task-1", "chat-1")])
    value = {"cowagent": "scheduler", "action": "disable", "task_id": "task-1"}

    first = handle_scheduler_action(value, store, {"chat-1"})
    second = handle_scheduler_action(value, store, {"chat-1"})

    assert store.enable_calls == [("task-1", False), ("task-1", False)]
    assert first["toast"] == {"type": "success", "content": "Task disabled"}
    assert second["card"]["type"] == "raw"
    refreshed_columns = next(
        element
        for element in second["card"]["data"]["body"]["elements"]
        if element.get("tag") == "column_set"
    )["columns"]
    assert refreshed_columns[0]["elements"][0]["value"]["action"] == "enable"


def test_action_rejects_task_from_another_receiver():
    store = FakeTaskStore([_task("task-1", "chat-2")])

    response = handle_scheduler_action(
        {"cowagent": "scheduler", "action": "delete", "task_id": "task-1"},
        store,
        {"chat-1", "user-1"},
    )

    assert response["toast"] == {"type": "error", "content": "Task is not available in this chat"}
    assert store.delete_calls == []


def test_action_rejects_mismatched_receiver_embedded_in_card_value():
    store = FakeTaskStore([_task("task-1", "user-1")])

    response = handle_scheduler_action(
        {
            "cowagent": "scheduler",
            "action": "delete",
            "task_id": "task-1",
            "receiver": "chat-1",
        },
        store,
        {"chat-1"},
    )

    assert response["toast"] == {"type": "error", "content": "Task is not available in this chat"}
    assert store.delete_calls == []


def test_delete_action_removes_owned_task():
    store = FakeTaskStore([_task("task-1", "user-1")])

    response = handle_scheduler_action(
        {"cowagent": "scheduler", "action": "delete", "task_id": "task-1"},
        store,
        {"user-1"},
    )

    assert store.delete_calls == ["task-1"]
    assert response["toast"] == {"type": "success", "content": "Task deleted"}
    assert "No scheduled tasks" in response["card"]["data"]["body"]["elements"][0]["content"]
