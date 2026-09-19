"""Regression tests for timezone-aware scheduler recurrence (#3145)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.scheduler_tool import SchedulerTool
from agent.tools.scheduler import time_utils


def _cron_task(expression, timezone_name=None):
    schedule = {"type": "cron", "expression": expression}
    if timezone_name:
        schedule["timezone"] = timezone_name
    return {"id": "task-1", "schedule": schedule}


def _utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_cron_keeps_local_wall_clock_across_melbourne_dst():
    """A UTC cron would drift one hour after Melbourne changes offset."""
    task = _cron_task("0 11 * * 5", "Australia/Melbourne")
    before = _utc("2026-10-02T00:30:00")  # 10:30 AEST, before the transition
    first = SchedulerService.__new__(SchedulerService)._calculate_next_run(task, before)

    assert first == _utc("2026-10-02T01:00:00")  # 11:00 +10:00

    after_first = first + timedelta(minutes=1)
    second = SchedulerService.__new__(SchedulerService)._calculate_next_run(task, after_first)
    assert second == _utc("2026-10-09T00:00:00")  # 11:00 +11:00


def test_spring_forward_nonexistent_local_time_shifts_to_real_instant():
    task = _cron_task("30 2 * * *", "America/New_York")
    before = _utc("2026-03-08T06:00:00")

    next_run = SchedulerService.__new__(SchedulerService)._calculate_next_run(task, before)

    # 02:30 does not exist; croniter advances to the next real wall time
    # (03:00 EDT). The following day returns to 02:30 EST.
    assert next_run == _utc("2026-03-08T07:00:00")
    following = SchedulerService.__new__(SchedulerService)._calculate_next_run(task, next_run)
    assert following == _utc("2026-03-09T06:30:00")


def test_fall_back_repeated_local_hour_does_not_run_task_twice():
    task = _cron_task("30 1 * * *", "America/New_York")
    # Start just after the first Saturday occurrence so the next calculation
    # reaches the repeated 01:30 wall-clock hour on the transition day.
    before = _utc("2026-10-31T05:31:00")

    service = SchedulerService.__new__(SchedulerService)
    first = service._calculate_next_run(task, before)
    after_first = first + timedelta(minutes=1)
    second = service._calculate_next_run(task, after_first)

    assert first == _utc("2026-11-01T05:30:00")
    assert second == _utc("2026-11-02T06:30:00")  # next daily occurrence


def test_aware_timestamps_are_normalized_to_utc():
    task = _cron_task("0 11 * * *", "Asia/Shanghai")
    task["next_run_at"] = "2026-10-02T11:00:00+08:00"
    task["last_run_at"] = "2026-10-02T10:00:00Z"

    normalized = time_utils.normalize_task_timestamps(task)

    assert normalized["next_run_at"] == "2026-10-02T03:00:00+00:00"
    assert normalized["last_run_at"] == "2026-10-02T10:00:00+00:00"


def test_legacy_naive_timestamp_keeps_declared_zone_meaning(monkeypatch):
    monkeypatch.setattr(
        time_utils,
        "resolve_timezone",
        lambda name=None: ZoneInfo("America/New_York"),
    )
    task = {"next_run_at": "2026-10-02T01:30:00"}

    normalized = time_utils.normalize_task_timestamps(task)

    assert normalized["next_run_at"] == "2026-10-02T05:30:00+00:00"


def test_service_compares_legacy_and_utc_timestamps_without_type_error(monkeypatch):
    task = _cron_task("0 9 * * *", "Asia/Shanghai")
    task["next_run_at"] = "2026-10-02T09:00:00+08:00"

    service = SchedulerService.__new__(SchedulerService)
    normalized = time_utils.normalize_task_timestamps(task)

    assert service._is_task_due(normalized, _utc("2026-10-02T01:05:00")) is True
    assert service._is_task_due(normalized, _utc("2026-10-02T00:59:59")) is False


def test_tool_uses_the_same_timezone_contract_for_initial_next_run():
    tool = SchedulerTool()
    schedule = tool._parse_schedule(
        "cron", "0 11 * * *", "Australia/Melbourne"
    )
    assert schedule == {
        "type": "cron",
        "expression": "0 11 * * *",
        "timezone": "Australia/Melbourne",
    }

    task = {"schedule": schedule}
    next_run = tool._calculate_next_run(task)
    assert next_run.tzinfo is not None
    assert next_run.utcoffset() == timezone.utc.utcoffset(None)
    assert next_run.astimezone(ZoneInfo("Australia/Melbourne")).hour == 11


def test_tool_rejects_unknown_iana_timezone():
    tool = SchedulerTool()

    assert tool._parse_schedule("cron", "0 11 * * *", "Not/A_Zone") is None


def test_once_absolute_timestamp_is_canonicalized_with_task_zone():
    tool = SchedulerTool()
    schedule = tool._parse_schedule(
        "once", "2026-10-02T11:00:00", "Australia/Melbourne"
    )

    assert schedule["run_at"] == "2026-10-02T01:00:00+00:00"
    assert schedule["timezone"] == "Australia/Melbourne"
