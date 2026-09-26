"""On-demand current-time tool.

Replacing the per-turn system-prompt time injection with this tool keeps the
system prompt byte-stable across turns, so server-side prefix caching stays
hot for the whole system prompt + conversation history.
"""
from datetime import datetime
import time as _time

from agent.tools.base_tool import BaseTool, ToolResult, ToolStage


class GetCurrentTimeTool(BaseTool):
    # Default decision stage is pre-process (offered to the model each turn).
    stage = ToolStage.PRE_PROCESS

    name = "get_current_time"
    description = (
        "获取当前精确日期与时间（含星期、时区）。"
        "凡涉及「今天 / 明天 / 现在几点 / 几月几号 / 多久之后 / 排程 / 相对时间」"
        "等任何与时间相关的推理，必须先调用本工具，切勿凭猜测作答。"
    )
    params = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self, params: dict) -> ToolResult:
        now = datetime.now()
        weekday_map = {
            "Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
            "Thursday": "星期四", "Friday": "星期五",
            "Saturday": "星期六", "Sunday": "星期日",
        }
        weekday = weekday_map.get(now.strftime("%A"), now.strftime("%A"))

        # Local UTC offset, e.g. UTC+8
        offset = -_time.altzone if _time.daylight else -_time.timezone
        sign = "+" if offset >= 0 else "-"
        hours = abs(offset) // 3600
        minutes = (abs(offset) % 3600) // 60
        tz = f"UTC{sign}{hours:02d}:{minutes:02d}" if minutes else f"UTC{sign}{hours:02d}"

        text = f"{now.strftime('%Y-%m-%d %H:%M:%S')} {weekday} ({tz})"
        return ToolResult.success(result=text)
