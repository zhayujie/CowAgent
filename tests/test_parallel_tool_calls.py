"""Several calls to one parallel-safe tool in a single turn.

Tools run in the order the model asked for them, which is what most of them
need. A model handed two independent jobs expresses that as two calls, though,
and for a tool whose whole point is that its calls are independent, running the
second only after the first finishes doubles the wait for nothing.
"""

import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.steer import SteerInbox
from agent.tools.base_tool import BaseTool, ToolResult


class _SlowTool(BaseTool):
    name = "slow"
    params = {"type": "object", "properties": {"tag": {"type": "string"}}}
    delay = 0.3

    def __init__(self):
        # Shared by every shallow copy, so a run can record the instance it
        # actually executed on.
        self.instances = []

    def execute(self, params):
        self.instances.append(self)
        time.sleep(self.delay)
        return ToolResult.success(params["tag"])


class _SlowParallelTool(_SlowTool):
    name = "slow_parallel"
    parallel_safe = True


def _executor(tool):
    executor = object.__new__(AgentStreamExecutor)
    executor.tools = {tool.name: tool}
    executor.model = None
    executor.agent = None
    executor.cancel_event = None
    executor._record_tool_result = lambda *a, **kw: None
    executor._check_consecutive_failures = lambda *a, **kw: (False, None, False)
    executor._emit_event = lambda *a, **kw: None
    return executor


def _calls(name, count):
    return [
        {"id": f"call_{i}", "name": name, "arguments": {"tag": f"t{i}"}}
        for i in range(count)
    ]


def test_parallel_safe_calls_run_at_the_same_time():
    tool = _SlowParallelTool()
    executor = _executor(tool)

    started = time.time()
    results = executor._run_parallel_calls(_calls(tool.name, 3))
    elapsed = time.time() - started

    assert sorted(results) == ["call_0", "call_1", "call_2"]
    assert [results[k]["result"] for k in sorted(results)] == ["t0", "t1", "t2"]
    # Serial would be 3 * delay; anything under two delays can only be overlap.
    assert elapsed < tool.delay * 2


def test_each_parallel_call_gets_its_own_tool_instance():
    """The loop drives tools by assignment - it sets cancel_event and
    progress_callback before a call and clears them after - so two concurrent
    calls sharing one instance would disarm and cross-report each other."""
    tool = _SlowParallelTool()
    executor = _executor(tool)

    executor._run_parallel_calls(_calls(tool.name, 2))

    assert len(tool.instances) == 2
    first, second = tool.instances
    assert first is not second
    assert tool not in tool.instances


def test_ordinary_tools_keep_running_in_order():
    tool = _SlowTool()
    executor = _executor(tool)

    assert executor._run_parallel_calls(_calls(tool.name, 3)) == {}
    assert tool.instances == []


def test_mixed_calls_are_not_prefetched():
    """Keep turns with ordinary tools on the sequential execution path."""
    parallel_tool = _SlowParallelTool()
    ordinary_tool = _SlowTool()
    executor = _executor(parallel_tool)
    executor.tools[ordinary_tool.name] = ordinary_tool

    calls = _calls(parallel_tool.name, 2) + [
        {"id": "call_2", "name": ordinary_tool.name, "arguments": {"tag": "t2"}},
    ]

    assert executor._run_parallel_calls(calls) == {}
    assert parallel_tool.instances == []
    assert ordinary_tool.instances == []


def test_a_lone_call_is_left_to_the_caller():
    """Nothing to overlap with, so it stays on the calling thread rather than
    paying for a pool and losing the loop's cancel checkpoint around it."""
    tool = _SlowParallelTool()
    executor = _executor(tool)

    assert executor._run_parallel_calls(_calls(tool.name, 1)) == {}
    assert tool.instances == []


def test_a_failing_call_does_not_take_its_siblings_down():
    class _Flaky(_SlowParallelTool):
        def execute(self, params):
            self.instances.append(self)
            if params["tag"] == "t0":
                raise RuntimeError("boom")
            return ToolResult.success(params["tag"])

    tool = _Flaky()
    executor = _executor(tool)

    results = executor._run_parallel_calls(_calls(tool.name, 2))

    assert len(results) == 2
    assert results["call_1"]["result"] == "t1"


def test_two_calls_are_in_flight_together():
    """Proves the overlap without leaning on wall-clock timing: the barrier
    only lets a call through once its sibling is inside as well, so were these
    run one after another both would fail on it."""
    barrier = threading.Barrier(2, timeout=3)
    threads = []

    class _Rendezvous(_SlowParallelTool):
        def execute(self, params):
            threads.append(threading.current_thread())
            barrier.wait()
            return ToolResult.success(params["tag"])

    executor = _executor(_Rendezvous())
    results = executor._run_parallel_calls(_calls("slow_parallel", 2))

    assert [r["status"] for r in results.values()] == ["success", "success"]
    assert threading.current_thread() not in threads


class _PrefetchedExecutor(AgentStreamExecutor):
    """Script the model turn and return tool results that were already prefetched."""

    def __init__(
        self,
        responses: list[tuple[str, list[dict[str, Any]]]],
        inbox: SteerInbox,
        results: dict[str, dict[str, Any]],
        on_prefetch: Callable[[list[dict[str, Any]]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Create an executor for result-loop regression tests.

        Args:
            responses: Scripted assistant text and tool-call pairs.
            inbox: Steering inbox used by the run.
            results: Results returned by the parallel prefetch step.
            on_prefetch: Optional callback invoked when prefetch completes.
            cancel_event: Optional cancellation event for the run.

        Returns:
            None.
        """
        super().__init__(
            agent=SimpleNamespace(),
            model=SimpleNamespace(model="scripted"),
            system_prompt="",
            tools=[],
            max_turns=4,
            messages=[],
            steer_inbox=inbox,
            cancel_event=cancel_event,
        )
        self.tools = {"slow_parallel": SimpleNamespace(parallel_safe=True)}
        self.responses = list(responses)
        self.prefetched_results = results
        self.on_prefetch = on_prefetch

    def _is_thinking_enabled(self) -> bool:
        """Disable model reasoning for the scripted test executor.

        Returns:
            False.
        """
        return False

    def _trim_messages(self) -> None:
        """Keep scripted test history unchanged.

        Returns:
            None.
        """
        return None

    def _validate_and_fix_messages(self) -> None:
        """Keep scripted test history unchanged.

        Returns:
            None.
        """
        return None

    def _call_llm_stream(self, retry_on_empty: bool = True) -> tuple[str, list[dict[str, Any]], str]:
        """Return the next scripted answer and append its assistant message.

        Args:
            retry_on_empty: Accepted for compatibility with the executor API.

        Returns:
            Assistant text, tool calls, and the stop reason.
        """
        text, tool_calls = self.responses.pop(0)
        content = [{"type": "text", "text": text}] if text else []
        content.extend({
            "type": "tool_use",
            "id": call["id"],
            "name": call["name"],
            "input": call["arguments"],
        } for call in tool_calls)
        self.messages.append({"role": "assistant", "content": content})
        return text, tool_calls, "tool_calls" if tool_calls else "stop"

    def _run_parallel_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Return scripted results from the prefetch step.

        Args:
            tool_calls: Tool calls proposed by the scripted assistant.

        Returns:
            Prefetched results keyed by tool-call ID.
        """
        if self.on_prefetch:
            self.on_prefetch(tool_calls)
        return self.prefetched_results


def test_steer_keeps_prefetched_parallel_results() -> None:
    """Preserve completed parallel results when steering arrives after prefetch.

    Returns:
        None.
    """
    inbox = SteerInbox()
    calls = _calls("slow_parallel", 2)
    results = {
        call["id"]: {"status": "success", "result": call["id"], "execution_time": 0.01}
        for call in calls
    }
    executor = _PrefetchedExecutor(
        [("", calls), ("redirected answer", [])],
        inbox,
        results,
        on_prefetch=lambda _: inbox.submit("change course"),
    )

    assert executor.run_stream("start") == "redirected answer"
    result_blocks = [
        block
        for message in executor.messages
        for block in (message.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert {block["tool_use_id"] for block in result_blocks} == {"call_0", "call_1"}
    assert all(not block.get("is_error", False) for block in result_blocks)


def test_cancel_keeps_completed_prefetched_result() -> None:
    """Preserve finished results and cancellation errors from parallel prefetch.

    Returns:
        None.
    """
    inbox = SteerInbox()
    cancel_event = threading.Event()
    calls = _calls("slow_parallel", 2)
    results = {
        "call_0": {"status": "success", "result": "finished", "execution_time": 0.01},
        "call_1": {"status": "error", "result": "still running; its result was discarded"},
    }
    executor = _PrefetchedExecutor(
        [("", calls)],
        inbox,
        results,
        on_prefetch=lambda _: cancel_event.set(),
        cancel_event=cancel_event,
    )

    executor.run_stream("start")
    result_blocks = {
        block["tool_use_id"]: block
        for message in executor.messages
        for block in (message.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    assert result_blocks["call_0"]["content"] == "finished"
    assert not result_blocks["call_0"].get("is_error", False)
    assert result_blocks["call_1"]["is_error"] is True
    assert "discarded" in result_blocks["call_1"]["content"]
