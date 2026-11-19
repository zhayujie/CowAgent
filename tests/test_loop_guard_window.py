# encoding:utf-8
"""The loop guard must catch alternating repetition, not just streaks.

All three counters in _check_consecutive_failures scan backwards and break
at the first entry of a different tool or arguments. An A, B, A, B, … loop —
the classic "read the file, re-run the test" spin, with every call
succeeding — therefore never accumulated more than 1: the hard guard never
fired and the run burned its whole max-turns budget. The soft hint reads a
sliding window and can see it, but a hint is droppable. This pins a hard
window count for the same tool+args pair.
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor


def _executor():
    agent = SimpleNamespace(name="test-agent", messages=[])
    return AgentStreamExecutor(
        agent=agent,
        model=SimpleNamespace(model="test-model"),
        system_prompt="",
        tools={},
        max_turns=10,
        messages=agent.messages,
    )


def _record(executor, name, args, success=True):
    executor._record_tool_result(name, args, success)


class LoopGuardWindowTest(unittest.TestCase):

    def test_an_alternating_loop_is_blocked(self):
        ex = _executor()
        # (read auth.py, pytest) × 4, then one more read: the same read call
        # appears 5 times in the last 10 entries but never twice in a row.
        for _ in range(4):
            _record(ex, "read", {"path": "auth.py"})
            _record(ex, "bash", {"command": "pytest -x"})
        _record(ex, "read", {"path": "auth.py"})

        should_stop, reason, is_critical = ex._check_consecutive_failures(
            "read", {"path": "auth.py"}
        )[:3]

        self.assertTrue(should_stop, "an alternating identical-call loop slipped through")
        self.assertFalse(is_critical)
        self.assertIn("交替", reason)

    def test_occasional_repeats_are_not_blocked(self):
        ex = _executor()
        # The same call 4 times in a window, mixed with varied work: below
        # the threshold, normal verification loops must keep running.
        for i in range(3):
            _record(ex, "read", {"path": "auth.py"})
            _record(ex, "bash", {"command": f"pytest -x -k test{i}"})
        _record(ex, "read", {"path": "auth.py"})

        should_stop, _, _ = ex._check_consecutive_failures(
            "read", {"path": "auth.py"}
        )[:3]

        self.assertFalse(should_stop)

    def test_a_pure_still_hits_the_original_rule_first(self):
        ex = _executor()
        for _ in range(5):
            _record(ex, "read", {"path": "auth.py"})

        should_stop, reason, _ = ex._check_consecutive_failures(
            "read", {"path": "auth.py"}
        )[:3]

        self.assertTrue(should_stop)
        self.assertNotIn("交替", reason)


if __name__ == "__main__":
    unittest.main()
