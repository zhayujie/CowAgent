"""A relative "+N unit" time must match fully, not as a prefix.

The relative-time parser used re.match, so "+1h30m" matched "+1h" and the
30m was silently dropped — the reminder fired an hour early with a success
message. "+30minutes" likewise became "+30m". Malformed values must be
refused at creation instead of being truncated into a different schedule.
"""

from agent.tools.scheduler.scheduler_tool import SchedulerTool
from bridge.context import Context, ContextType


class _TaskStore:
    def __init__(self):
        self.tasks = []

    def add_task(self, task):
        self.tasks.append(task)


def _tool():
    tool = SchedulerTool({"channel_type": "web"})
    context = Context(ContextType.TEXT, "hello")
    context["channel_type"] = "web"
    context["receiver"] = "web-session"
    context["session_id"] = "web-session"
    context["isgroup"] = False
    tool.current_context = context
    tool.task_store = _TaskStore()
    return tool


def _create(tool, schedule_value):
    return tool._create_task(
        name="Reminder",
        message="Stand up",
        schedule_type="once",
        schedule_value=schedule_value,
    )


def test_compound_relative_time_is_refused_not_truncated():
    tool = _tool()
    result = _create(tool, "+1h30m")
    assert "错误" in result, result
    assert tool.task_store.tasks == [], "a truncated '+1h30m' must not become a +1h task"


def test_unit_word_suffix_is_refused_not_truncated():
    tool = _tool()
    result = _create(tool, "+30minutes")
    assert "错误" in result, result
    assert tool.task_store.tasks == []


def test_a_wellformed_relative_time_is_still_created():
    tool = _tool()
    result = _create(tool, "+5m")
    assert "创建成功" in result, result
    assert len(tool.task_store.tasks) == 1
