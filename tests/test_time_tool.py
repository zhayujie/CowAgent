# encoding:utf-8
"""The system prompt carries only the date; the clock is served by a tool.

A clock in ``messages[0]`` would change on every turn and void the provider's
prefix cache for the whole conversation, so both halves are pinned here: the
tool answers with a precise local time, and the runtime section renders the
date but never a time of day.
"""
import re

from agent.prompt.builder import _build_runtime_section, _build_tooling_section
from agent.tools.current_time.current_time import TimeTool, current_time_info


def _fixed_time_info():
    return {"date": "2026-09-26", "time": "12:34:56", "weekday": "星期六", "timezone": "UTC+08"}


def test_tool_returns_precise_local_time():
    result = TimeTool().execute({})

    assert result.status == "success"
    text = result.result
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+ \(UTC[+-]\d{2}(:\d{2})?\)", text), text


def test_time_info_shape():
    info = current_time_info()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", info["date"])
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", info["time"])
    assert re.fullmatch(r"UTC[+-]\d{2}(:\d{2})?", info["timezone"])
    assert info["weekday"]


def test_runtime_section_renders_date_without_clock():
    lines = _build_runtime_section({"_get_current_time": _fixed_time_info, "model": "test-model"}, "zh")
    joined = "\n".join(lines)

    assert "当前日期: 2026-09-26 星期六 (UTC+08)" in joined
    assert "12:34" not in joined
    assert "当前时间" not in joined
    assert "test-model" in joined


def test_runtime_section_en_label():
    info = {**_fixed_time_info(), "weekday": "Saturday"}
    lines = _build_runtime_section({"_get_current_time": lambda: info}, "en")

    assert "Current date: 2026-09-26 Saturday (UTC+08)" in "\n".join(lines)


def test_runtime_section_is_stable_within_a_day():
    runtime_info = {"_get_current_time": _fixed_time_info, "model": "m"}
    first = _build_runtime_section(runtime_info, "zh")
    runtime_info["_get_current_time"] = lambda: {**_fixed_time_info(), "time": "23:59:59"}

    assert _build_runtime_section(runtime_info, "zh") == first


def test_tool_is_listed_with_summary():
    joined = "\n".join(_build_tooling_section([TimeTool()], "zh"))

    assert "- time: 获取当前日期和时间" in joined
