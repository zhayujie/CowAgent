"""A task that comes due while another task is running must still execute.

The scheduler runs every due task inline on its own loop thread, and
``_is_task_due`` drops any cron occurrence that is more than ten minutes late.
So when one agent task blocks the loop for longer than that window, a task that
came due meanwhile is logged as overdue and rescheduled to its next occurrence
without ever running. The ten-minute window is there to swallow occurrences
missed while the process was away; it must not swallow ones the loop itself
caused by being busy.
"""

from datetime import datetime, timedelta, timezone

import pytest

from agent.tools.scheduler import scheduler_service
from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.task_store import TaskStore


class Clock(datetime):
    """A datetime whose "now" the test moves forward while a task runs."""

    current = datetime(2026, 11, 4, 9, 0, 10)

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


def _task(tid, cron, next_run, created, zone=None):
    schedule = {"type": "cron", "expression": cron}
    if zone:
        schedule["timezone"] = zone
    return {
        "id": tid,
        "name": tid,
        "enabled": True,
        "created_at": created,
        "next_run_at": next_run,
        "schedule": schedule,
        "action": {"type": "send_message", "content": "hi"},
    }


def _store(tmp_path, tasks):
    store = TaskStore(str(tmp_path / "tasks.json"))
    for task in tasks:
        store.add_task(task)
    return store


def _as_utc(naive):
    """Store a legacy wall clock the way a declared-zone task persists it."""
    return naive.astimezone(timezone.utc).isoformat()


def test_a_task_that_came_due_during_a_long_run_still_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", Clock)
    Clock.current = datetime(2026, 11, 4, 9, 0, 10)
    store = _store(
        tmp_path,
        [
            # Newest first in list_tasks(), so the digest is the blocking run.
            _task("digest", "0 9 * * *", "2026-11-04T09:00:00", "2026-11-01T00:00:00"),
            _task("standup", "5 9 * * *", "2026-11-04T09:05:00", "2026-10-01T00:00:00"),
        ],
    )
    ran = []

    def execute(task):
        ran.append(task["id"])
        if task["id"] == "digest":
            # A 20-minute agent task: the loop cannot tick until it returns.
            Clock.current = Clock.current + timedelta(minutes=20)
        return True

    service = SchedulerService(store, execute)
    service._check_and_execute_tasks()  # 09:00:10 — digest runs until 09:20:10
    service._check_and_execute_tasks()  # 09:20:10 — standup is 15 minutes late

    assert ran == ["digest", "standup"]
    assert store.get_task("standup")["next_run_at"].startswith("2026-11-05T09:05")


def test_a_zoned_task_that_came_due_during_a_long_run_still_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler_service, "datetime", Clock)
    Clock.current = datetime(2026, 11, 4, 9, 0, 10)
    store = _store(
        tmp_path,
        [
            _task(
                "digest",
                "0 9 * * *",
                _as_utc(datetime(2026, 11, 4, 9, 0)),
                "2026-11-01T00:00:00",
                zone="UTC",
            ),
            _task(
                "standup",
                "5 9 * * *",
                _as_utc(datetime(2026, 11, 4, 9, 5)),
                "2026-10-01T00:00:00",
                zone="UTC",
            ),
        ],
    )
    ran = []

    def execute(task):
        ran.append(task["id"])
        if task["id"] == "digest":
            Clock.current = Clock.current + timedelta(minutes=20)
        return True

    service = SchedulerService(store, execute)
    service._check_and_execute_tasks()
    service._check_and_execute_tasks()

    assert ran == ["digest", "standup"]


def test_an_occurrence_missed_while_the_process_was_away_is_still_skipped(
    tmp_path, monkeypatch
):
    """The catch-up window keeps swallowing genuinely stale occurrences."""
    monkeypatch.setattr(scheduler_service, "datetime", Clock)
    Clock.current = datetime(2026, 11, 4, 14, 0, 0)
    store = _store(
        tmp_path,
        [_task("morning", "30 9 * * *", "2026-11-04T09:30:00", "2026-10-01T00:00:00")],
    )
    ran = []

    def execute(task):
        ran.append(task["id"])
        return True

    SchedulerService(store, execute)._check_and_execute_tasks()

    assert ran == []
    assert store.get_task("morning")["next_run_at"].startswith("2026-11-05T09:30")


@pytest.mark.parametrize("late_by", [timedelta(minutes=11), timedelta(hours=3)])
def test_the_blocking_run_rescues_an_occurrence_however_late(
    tmp_path, monkeypatch, late_by
):
    """Lateness caused by the loop itself is recovered, not capped at 10 minutes."""
    monkeypatch.setattr(scheduler_service, "datetime", Clock)
    Clock.current = datetime(2026, 11, 4, 9, 0, 10)
    store = _store(
        tmp_path,
        [
            _task("digest", "0 9 * * *", "2026-11-04T09:00:00", "2026-11-01T00:00:00"),
            _task("standup", "5 9 * * *", "2026-11-04T09:05:00", "2026-10-01T00:00:00"),
        ],
    )
    ran = []

    def execute(task):
        ran.append(task["id"])
        if task["id"] == "digest":
            Clock.current = Clock.current + late_by
        return True

    service = SchedulerService(store, execute)
    service._check_and_execute_tasks()
    service._check_and_execute_tasks()

    assert ran == ["digest", "standup"]
