"""Regression: a task whose stored `schedule` is not a mapping must not raise.

`task.get("schedule", {})` only substitutes the default when the key is absent.
A key present with a null or a bare string left None in place, and the chained
`.get("timezone")` raised AttributeError from every scheduler read path."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.scheduler.time_utils import (  # noqa: E402
    normalize_task_timestamps,
    scheduled_reference_time,
    task_timezone,
)


class TestTaskTimezoneToleratesANonMappingSchedule:
    def test_a_null_schedule_is_legacy_mode_not_a_crash(self):
        assert task_timezone({"schedule": None}) is None

    def test_a_string_schedule_is_legacy_mode_not_a_crash(self):
        assert task_timezone({"schedule": "daily"}) is None

    def test_a_list_or_number_schedule_is_legacy_mode_not_a_crash(self):
        for bad in ([], 0, 3.5, True):
            assert task_timezone({"schedule": bad}) is None

    def test_an_absent_schedule_is_still_legacy_mode(self):
        assert task_timezone({}) is None

    def test_a_real_timezone_is_still_honoured(self):
        zone = task_timezone({"schedule": {"type": "cron", "timezone": "UTC"}})
        assert zone is not None
        assert getattr(zone, "key", str(zone)) == "UTC"

    def test_normalize_task_timestamps_survives_a_null_schedule(self):
        # This is the call the scheduler loop makes for every task on every tick.
        task = {"id": "t1", "schedule": None,
                "next_run_at": "2099-01-01T09:00:00"}
        out = normalize_task_timestamps(task)
        assert out["next_run_at"] == "2099-01-01T09:00:00"

    def test_scheduled_reference_time_survives_a_null_schedule(self):
        now = datetime(2099, 1, 1, 9, 0, 0)
        out = scheduled_reference_time({"schedule": None}, now)
        assert isinstance(out, datetime)

    def test_a_zoned_task_still_normalizes_to_utc(self):
        task = {"id": "t1", "schedule": {"type": "cron", "timezone": "UTC"},
                "next_run_at": "2099-01-01T09:00:00+00:00"}
        out = normalize_task_timestamps(task)
        parsed = datetime.fromisoformat(out["next_run_at"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)
        assert parsed == datetime(2099, 1, 1, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# the tool's own read paths, not just the loop's helpers
# ---------------------------------------------------------------------------


def _store_with(tmp_path, tasks):
    """A real TaskStore whose file already holds *tasks* (id -> record)."""
    import json

    from agent.tools.scheduler.task_store import TaskStore

    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    return TaskStore(str(path))


def _tool(store):
    from agent.tools.scheduler.scheduler_tool import SchedulerTool

    tool = SchedulerTool({"channel_type": "web", "agent_id": ""})
    tool.task_store = store
    return tool


def _good_task():
    return {
        "id": "good", "name": "good", "enabled": True,
        "created_at": "2099-01-01T09:00:00",
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "action": {"type": "send_message", "content": "hi"},
    }


def _broken_task():
    return {
        "id": "bad", "name": "bad", "enabled": True, "schedule": None,
        "created_at": "2099-01-01T09:00:00",
        "action": {"type": "send_message", "content": "hi"},
    }


def test_list_survives_a_task_whose_schedule_is_not_a_mapping(tmp_path):
    store = _store_with(tmp_path, {"good": _good_task(), "bad": _broken_task()})

    result = _tool(store).execute({"action": "list"})

    assert result.status == "success", f"one bad record took the whole list down: {result.result}"
    assert "good" in result.result and "bad" in result.result


def test_get_survives_a_task_whose_schedule_is_not_a_mapping(tmp_path):
    store = _store_with(tmp_path, {"bad": _broken_task()})

    result = _tool(store).execute({"action": "get", "task_id": "bad"})

    assert result.status == "success", f"the bad task cannot even be inspected: {result.result}"
    assert "bad" in result.result


def test_a_string_schedule_also_reads_as_unknown(tmp_path):
    broken = _broken_task()
    broken["schedule"] = "daily"
    store = _store_with(tmp_path, {"bad": broken})

    result = _tool(store).execute({"action": "list"})

    assert result.status == "success", result.result
    assert "未知" in result.result


def test_a_real_cron_is_still_described(tmp_path):
    store = _store_with(tmp_path, {"good": _good_task()})

    result = _tool(store).execute({"action": "list"})

    assert result.status == "success"
    assert "每天 9:00" in result.result
