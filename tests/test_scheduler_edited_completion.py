"""Finishing an old occurrence must not consume a user's edited schedule."""

from datetime import datetime, timedelta, timezone

import pytest

from agent.tools.scheduler import scheduler_service
from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.task_store import TaskStore

FIXED = datetime(2026, 1, 15, 12)
FUTURE = "2050-01-01T12:00:00"


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED if tz is None else FIXED.astimezone(tz)


def due_store(tmp_path, kind="once", zone=None):
    store = TaskStore(str(tmp_path / "tasks.json"))
    instant = FIXED.astimezone(timezone.utc) if zone else FIXED
    due = (instant - timedelta(seconds=1)).replace(tzinfo=None).isoformat()
    schedule = {"type": kind}
    schedule.update({"run_at": due} if kind == "once" else {"seconds": 300})
    if zone:
        schedule["timezone"] = zone
    store.add_task(
        {
            "id": "reminder",
            "name": "Original reminder",
            "enabled": True,
            "schedule": schedule,
            "next_run_at": due,
        }
    )
    return store


@pytest.mark.parametrize("kind", ["once", "interval"])
def test_execution_completion_preserves_rescheduled_task(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path, kind)
    edited_schedule = {"type": "interval", "seconds": 900}
    observed = []

    def execute(task):
        observed.append(task["id"])
        # Real persistence mutation at the callback boundary, as a Web edit
        # arriving while the Agent is completing its prior occurrence.
        store.update_task(
            task["id"], {"schedule": edited_schedule, "next_run_at": FUTURE}
        )
        return True

    SchedulerService(store, execute)._check_and_execute_tasks()
    assert observed == ["reminder"]
    saved = store.get_task("reminder")
    assert saved is not None
    assert saved["schedule"] == edited_schedule
    assert saved["next_run_at"] == FUTURE
    # Prove the replacement survived reopening the real JSON store too.
    assert TaskStore(store.store_path).get_task("reminder") == saved


@pytest.mark.parametrize("kind", ["once", "interval"])
@pytest.mark.parametrize("zone", [None, "UTC"])
def test_unchanged_occurrence_still_finishes(tmp_path, monkeypatch, kind, zone):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path, kind, zone)
    observed = []
    SchedulerService(
        store, lambda task: observed.append(task["id"])
    )._check_and_execute_tasks()
    assert observed == ["reminder"]
    saved = store.get_task("reminder")
    if kind == "once":
        assert saved is None
    else:
        reference = FIXED.astimezone(timezone.utc) if zone else FIXED
        assert saved["next_run_at"] == (reference + timedelta(seconds=300)).isoformat()


def test_failed_occurrence_preserves_callback_reschedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path)

    def execute(task):
        store.update_task(task["id"], {"next_run_at": FUTURE})
        return False

    SchedulerService(store, execute)._check_and_execute_tasks()
    assert store.get_task("reminder")["next_run_at"] == FUTURE


def test_disabling_inflight_once_task_keeps_it_available(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path)

    def execute(task):
        store.update_task(task["id"], {"enabled": False})

    SchedulerService(store, execute)._check_and_execute_tasks()
    assert store.get_task("reminder")["enabled"] is False


def test_renaming_does_not_prevent_interval_advance(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path, "interval")

    def execute(task):
        store.update_task(task["id"], {"name": "Renamed reminder"})

    SchedulerService(store, execute)._check_and_execute_tasks()
    saved = store.get_task("reminder")
    assert saved["name"] == "Renamed reminder"
    assert saved["next_run_at"] == (FIXED + timedelta(seconds=300)).isoformat()


def test_deleting_inflight_task_does_not_recreate_it(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path)

    def execute(task):
        store.delete_task(task["id"])

    SchedulerService(store, execute)._check_and_execute_tasks()
    assert store.get_task("reminder") is None


def test_postponing_only_next_occurrence_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path, "interval")
    schedule = store.get_task("reminder")["schedule"]

    def execute(task):
        store.update_task(task["id"], {"next_run_at": FUTURE})

    SchedulerService(store, execute)._check_and_execute_tasks()
    saved = store.get_task("reminder")
    assert saved["next_run_at"] == FUTURE
    assert saved["schedule"] == schedule


def test_explicit_default_enabled_does_not_block_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", FixedDatetime)
    store = due_store(tmp_path, "interval")
    tasks = store.load_tasks()
    tasks["reminder"].pop("enabled")
    store.save_tasks(tasks)

    def execute(task):
        store.update_task(task["id"], {"enabled": True, "name": "Updated"})

    SchedulerService(store, execute)._check_and_execute_tasks()
    assert (
        store.get_task("reminder")["next_run_at"]
        == (FIXED + timedelta(seconds=300)).isoformat()
    )
