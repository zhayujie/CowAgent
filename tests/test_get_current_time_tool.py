# encoding:utf-8
"""Current time is served on demand, not injected into the system prompt.

Keeping the time out of ``messages[0]`` is what lets server-side prefix
caching cover the whole system prompt plus the conversation history, so both
halves of the change are pinned here: the tool answers with a precise local
time, and the runtime section no longer renders one at all.
"""
import re

from agent.prompt.builder import _build_runtime_section
from agent.tools.datetime.get_current_time import GetCurrentTimeTool


def test_tool_returns_precise_local_time():
    result = GetCurrentTimeTool().execute({})

    assert result.status == "success"
    text = result.result
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text), text
    assert re.search(r"星期[一二三四五六日]", text), text
    assert re.search(r"\(UTC[+-]\d{2}(:\d{2})?\)", text), text


def test_runtime_section_no_longer_renders_time():
    lines = _build_runtime_section(
        {
            "_get_current_time": lambda: {
                "time": "2026-09-26 12:00:00",
                "weekday": "星期六",
                "timezone": "UTC+08",
            },
            "model": "test-model",
        },
        "zh",
    )
    joined = "\n".join(lines)

    assert "当前时间" not in joined
    assert "2026-09-26" not in joined
    # The rest of the section is still built.
    assert "test-model" in joined
