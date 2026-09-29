"""On-demand current-time tool.

The system prompt carries only today's date: a clock there would change on
every turn and void the provider's prefix cache for the whole conversation.
The exact time is served here instead, when a task actually depends on it.
"""
import datetime
from typing import Dict

from agent.tools.base_tool import BaseTool, ToolResult

_WEEKDAYS_ZH = {
    "Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
    "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日",
}


def current_time_info() -> Dict[str, str]:
    """Local date, time, weekday and UTC offset, formatted for the model."""
    now = datetime.datetime.now().astimezone()

    offset = int(now.utcoffset().total_seconds())
    sign = "+" if offset >= 0 else "-"
    hours, minutes = divmod(abs(offset) // 60, 60)
    timezone = f"UTC{sign}{hours:02d}:{minutes:02d}" if minutes else f"UTC{sign}{hours:02d}"

    weekday = now.strftime("%A")
    try:
        from common import i18n
        is_en = i18n.get_language() == "en"
    except Exception:
        is_en = False
    if not is_en:
        weekday = _WEEKDAYS_ZH.get(weekday, weekday)

    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday,
        "timezone": timezone,
    }


class TimeTool(BaseTool):
    """Tool for reading the current local time"""

    name: str = "time"
    description: str = (
        "Get the current local date and time, with weekday and timezone. "
        "Only today's date is given elsewhere, so call this first whenever the answer "
        "depends on the time of day: what time it is, how long until or since something, "
        "whether a time today has already passed, or when to schedule a reminder or task. "
        "Never guess the time."
    )

    params: dict = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self, args: dict) -> ToolResult:
        info = current_time_info()
        return ToolResult.success(f"{info['date']} {info['time']} {info['weekday']} ({info['timezone']})")
