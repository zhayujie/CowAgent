"""A cancel ends the parallel tool prefetch without waiting for the slow calls."""

import threading
import time

import pytest

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.base_tool import BaseTool, ToolResult


class _GatedTool(BaseTool):
    """Returns at once for tags in `quick`, raises for "boom", else blocks until released."""

    name = "gated"
    parallel_safe = True
    params = {"type": "object", "properties": {"tag": {"type": "string"}}}

    def __init__(self, release, quick=()):
        self.release = release
        self.quick = set(quick)
        self.finished = []

    def execute(self, params):
        tag = params["tag"]
        if tag == "boom":
            raise RuntimeError("boom")
        if tag not in self.quick:
            self.release.wait(timeout=30)
        self.finished.append(tag)
        return ToolResult.success(tag)


def _executor(tool, cancel_event=None):
    executor = object.__new__(AgentStreamExecutor)
    executor.tools = {tool.name: tool}
    executor.model = None
    executor.agent = None
    executor.cancel_event = cancel_event
    executor._record_tool_result = lambda *a, **kw: None
    executor._check_consecutive_failures = lambda *a, **kw: (False, None, False, False)
    executor._emit_event = lambda *a, **kw: None
    return executor


def _calls(tags):
    return [{"id": f"call_{i}", "name": "gated", "arguments": {"tag": t}} for i, t in enumerate(tags)]


@pytest.fixture
def release():
    event = threading.Event()
    yield event
    event.set()


def test_cancel_returns_while_a_worker_is_still_running(release):
    cancel = threading.Event()
    tool = _GatedTool(release, quick={"quick"})
    threading.Timer(0.3, cancel.set).start()

    started = time.time()
    results = _executor(tool, cancel)._run_parallel_calls(_calls(["quick", "stuck"]))

    assert time.time() - started < 5
    assert tool.finished == ["quick"]
    assert results["call_0"]["status"] == "success" and results["call_0"]["result"] == "quick"
    assert results["call_1"]["status"] == "error" and "discarded" in results["call_1"]["result"]


def test_without_a_cancel_every_call_is_waited_for(release):
    threading.Timer(0.1, release.set).start()
    results = _executor(_GatedTool(release), threading.Event())._run_parallel_calls(_calls(["t0", "t1"]))
    assert sorted(r["result"] for r in results.values()) == ["t0", "t1"]


def test_a_raising_call_keeps_its_error_to_its_own_id(release):
    release.set()
    results = _executor(_GatedTool(release))._run_parallel_calls(_calls(["boom", "t1"]))
    assert results["call_0"]["status"] == "error" and "boom" in results["call_0"]["result"]
    assert results["call_1"]["result"] == "t1"
