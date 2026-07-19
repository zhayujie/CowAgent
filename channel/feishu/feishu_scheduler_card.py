"""Feishu scheduler card rendering and callback handling."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set


_MAX_TASKS = 20


def tasks_for_receivers(tasks: Iterable[dict], receivers: Set[str]) -> List[dict]:
    """Return Feishu tasks owned by one of the callback's trusted receivers."""
    visible = []
    for task in tasks:
        action = task.get("action") or {}
        if action.get("channel_type") != "feishu":
            continue
        if action.get("receiver") in receivers:
            visible.append(task)
    return visible


def build_scheduler_card(
    tasks: Iterable[dict], agent_id: str = None
) -> Dict[str, Any]:
    """Build a Card 2.0 task list with explicit, idempotent actions."""
    task_list = list(tasks)
    elements: List[Dict[str, Any]] = []

    if not task_list:
        elements.append({"tag": "markdown", "content": "No scheduled tasks in this chat."})
    else:
        for index, task in enumerate(task_list[:_MAX_TASKS]):
            if index:
                elements.append({"tag": "hr"})
            task_id = str(task.get("id") or "")
            receiver = str((task.get("action") or {}).get("receiver") or "")
            enabled = task.get("enabled", True)
            status = "Enabled" if enabled else "Disabled"
            next_run = str(task.get("next_run_at") or "Unknown").replace("T", " ")
            elements.append(
                {
                    "tag": "markdown",
                    "content": "**{}** · {}\n`{}` · {}\nNext: {}".format(
                        task.get("name") or "Unnamed task",
                        status,
                        task_id,
                        _format_schedule(task.get("schedule") or {}),
                        next_run,
                    ),
                }
            )
            toggle_action = "disable" if enabled else "enable"
            toggle_text = "Disable" if enabled else "Enable"
            toggle_type = "default" if enabled else "primary"
            elements.append(
                {
                    "tag": "column_set",
                    "columns": [
                        {
                            "tag": "column",
                            "elements": [
                                _button(
                                    toggle_text,
                                    toggle_type,
                                    toggle_action,
                                    task_id,
                                    receiver,
                                    agent_id,
                                )
                            ],
                        },
                        {
                            "tag": "column",
                            "elements": [
                                _button(
                                    "Delete",
                                    "danger",
                                    "delete",
                                    task_id,
                                    receiver,
                                    agent_id,
                                )
                            ],
                        },
                    ],
                }
            )

        hidden = len(task_list) - _MAX_TASKS
        if hidden > 0:
            elements.extend(
                [
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": "{} more tasks are hidden.".format(hidden),
                        "text_size": "notation",
                    },
                ]
            )

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "enable_forward_interaction": False},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "Scheduled tasks"},
        },
        "body": {"elements": elements},
    }


def handle_scheduler_action(
    value: Dict[str, Any],
    task_store: Any,
    allowed_receivers: Set[str],
    agent_id: str = None,
) -> Dict[str, Any]:
    """Apply an owned scheduler action and return a Feishu callback response."""
    if value.get("cowagent") != "scheduler":
        return {}

    task_id = str(value.get("task_id") or "")
    action = value.get("action")
    if not task_id or action not in {"enable", "disable", "delete"}:
        return _toast("error", "Invalid scheduler action")

    task = task_store.get_task(task_id)
    if not task:
        return _response(
            "info",
            "Task no longer exists",
            build_scheduler_card(
                tasks_for_receivers(task_store.list_tasks(), allowed_receivers),
                agent_id=agent_id,
            ),
        )

    task_receiver = (task.get("action") or {}).get("receiver")
    task_channel = (task.get("action") or {}).get("channel_type")
    value_receiver = value.get("receiver")
    if (
        task_channel != "feishu"
        or task_receiver not in allowed_receivers
        or (value_receiver and value_receiver != task_receiver)
    ):
        return _toast("error", "Task is not available in this chat")

    try:
        if action == "delete":
            task_store.delete_task(task_id)
            message = "Task deleted"
        else:
            enabled = action == "enable"
            task_store.enable_task(task_id, enabled)
            message = "Task enabled" if enabled else "Task disabled"
    except (OSError, ValueError) as exc:
        return _toast("error", "Task update failed: {}".format(exc))

    visible = tasks_for_receivers(task_store.list_tasks(), allowed_receivers)
    return _response(
        "success", message, build_scheduler_card(visible, agent_id=agent_id)
    )


def _response(toast_type: str, content: str, card: Dict[str, Any]) -> Dict[str, Any]:
    response = _toast(toast_type, content)
    response["card"] = {"type": "raw", "data": card}
    return response


def _toast(toast_type: str, content: str) -> Dict[str, Any]:
    return {"toast": {"type": toast_type, "content": content}}


def _button(
    text: str,
    button_type: str,
    action: str,
    task_id: str,
    receiver: str,
    agent_id: str = None,
) -> Dict[str, Any]:
    value = {
        "cowagent": "scheduler",
        "action": action,
        "task_id": task_id,
        "receiver": receiver,
    }
    if agent_id:
        value["agent_id"] = agent_id
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "value": value,
    }


def _format_schedule(schedule: Dict[str, Any]) -> str:
    schedule_type = schedule.get("type")
    if schedule_type == "cron":
        return "cron {}".format(schedule.get("expression") or "?")
    if schedule_type == "interval":
        return "every {}s".format(schedule.get("seconds") or "?")
    if schedule_type == "once":
        return "once at {}".format(schedule.get("run_at") or "?")
    return str(schedule_type or "unknown schedule")
