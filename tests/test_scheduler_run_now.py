"""Tests for immediate execution of persisted scheduler tasks."""

import threading
import time
from datetime import datetime, timedelta

import pytest

from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.scheduler_tool import SchedulerTool
from agent.tools.scheduler.task_store import TaskStore


def _task(task_id="task-1", enabled=False):
    return {
        "id": task_id,
        "name": "refresh index",
        "enabled": enabled,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "next_run_at": (datetime.now() + timedelta(hours=2)).isoformat(),
        "schedule": {"type": "interval", "seconds": 7200},
        "action": {"type": "send_message", "content": "done"},
    }


def test_manual_run_executes_disabled_task_without_moving_schedule(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.json"))
    task = _task()
    store.add_task(task)
    completed = threading.Event()

    def execute(received):
        assert received["id"] == "task-1"
        completed.set()
        return True

    service = SchedulerService(store, execute)
    service.run_task_now("task-1")

    assert completed.wait(timeout=2)
    deadline = time.time() + 2
    while time.time() < deadline:
        updated = store.get_task("task-1")
        if updated.get("last_manual_run_at"):
            break
        time.sleep(0.01)

    updated = store.get_task("task-1")
    assert updated["next_run_at"] == task["next_run_at"]
    assert updated["enabled"] is False
    assert updated["last_run_at"] == updated["last_manual_run_at"]


def test_manual_run_rejects_duplicate_execution(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.json"))
    store.add_task(_task())
    release = threading.Event()
    started = threading.Event()

    def execute(_task_data):
        started.set()
        release.wait(timeout=2)
        return True

    service = SchedulerService(store, execute)
    service.run_task_now("task-1")
    assert started.wait(timeout=2)
    with pytest.raises(RuntimeError, match="already running"):
        service.run_task_now("task-1")
    release.set()


def test_scheduler_tool_does_not_expose_manual_execution():
    actions = SchedulerTool.params["properties"]["action"]["enum"]

    assert "run" not in actions


def test_scheduler_stop_wakes_sleeping_loop_immediately(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.json"))
    service = SchedulerService(store, lambda _task_data: True)
    service.start()
    started_at = time.monotonic()

    service.stop()

    assert time.monotonic() - started_at < 0.5
    assert service.thread is not None
    assert not service.thread.is_alive()
