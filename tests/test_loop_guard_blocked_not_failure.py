# encoding:utf-8
"""A repetition block is the guardrail talking, not a tool failure.

The loop guard blocks the 6th identical tool call (5 consecutive same-args
calls) and returns an error result the model can adapt to. The block itself
used to be recorded into tool_failure_history as a *failure*. Those synthetic
failures poisoned the same-tool failure counters: after a stubborn model's
blocked retries, the next *different-arguments* call — a fresh attempt at a
tool that had never actually failed — was refused by the 6-failure rule, and
enough of them escalated to the run-aborting critical status. The
permission-refusal path in the same function documents the principle
("deliberately not recorded as a tool failure"); this pins the same for
repetition blocks, while failure-based blocks keep recording so genuine
failures still escalate.
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.base_tool import ToolResult


class _EchoTool:
    name = "echo"

    def __init__(self):
        self.executions = 0

    def execute_tool(self, args):
        self.executions += 1
        return ToolResult.success("ok")


class _Executor(AgentStreamExecutor):
    """Real tool-execution path with the noisy neighbours stubbed out."""

    def __init__(self):
        agent = SimpleNamespace(name="test-agent", messages=[])
        super().__init__(
            agent=agent,
            model=SimpleNamespace(model="test-model"),
            system_prompt="",
            tools={},
            max_turns=20,
            messages=agent.messages,
        )
        self.cancel_event = None
        self.echo = _EchoTool()
        self.tools = {"echo": self.echo}

    def _permission_denial(self, tool_name, arguments):
        return None

    def _emit_event(self, event_type, data=None):
        pass

    def _is_thinking_enabled(self):
        return False


class LoopGuardBlockedNotFailureTest(unittest.TestCase):

    def test_a_fresh_call_after_blocked_retries_still_runs(self):
        # The loop: five identical *successful* calls, then the model
        # stubbornly re-sends the same call a few more times (blocked each
        # time), then finally tries genuinely different arguments.
        executor = _Executor()
        for i in range(11):
            executor._execute_tool({"id": f"c{i}", "name": "echo", "arguments": {"x": 1}})

        # The fresh, different-args attempt: the tool never actually failed,
        # so this must execute — but synthetic "failures" recorded for the
        # blocked retries made the 6-failure rule refuse it.
        result = executor._execute_tool({"id": "fresh", "name": "echo", "arguments": {"x": 2}})

        self.assertEqual(result["status"], "success")
        # Five real executions from the loop plus the fresh one.
        self.assertEqual(executor.echo.executions, 6)

    def test_blocked_repetitions_keep_the_guard_active(self):
        # The block itself must keep firing for identical retries — refusing
        # to record them as failures must not disable the repetition rule.
        executor = _Executor()
        statuses = [
            executor._execute_tool({"id": f"c{i}", "name": "echo", "arguments": {"x": 1}})["status"]
            for i in range(12)
        ]
        self.assertEqual(statuses[:5], ["success"] * 5)
        self.assertTrue(all(s == "error" for s in statuses[5:]), statuses)
        self.assertEqual(executor.echo.executions, 5)

    def test_real_failures_still_escalate(self):
        # Failure-based blocks keep recording, so the critical abort stays
        # reachable for genuinely failing tools.
        executor = _Executor()

        def failing(args):
            return ToolResult.fail("boom")

        executor.echo.execute_tool = failing
        statuses = [
            executor._execute_tool(
                {"id": f"call-{i}", "name": "echo", "arguments": {"x": i}}
            )["status"]
            for i in range(9)
        ]
        self.assertIn("critical_error", statuses)


if __name__ == "__main__":
    unittest.main()
