"""Regression tests for empty replies produced by scheduled tasks.

A scheduled task may legitimately have nothing to report ("notify me only if
the price drops"). Such a run must stay silent instead of delivering the
generic "I can't generate a reply" fallback to a user who never asked
anything.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.scheduler.integration import _execute_agent_task


def _make_executor(allow_empty_response):
    agent = SimpleNamespace(
        name="test-agent",
        messages=[],
        tools=[],
        workspace_dir=None,
        _current_session_id="scheduler_task-1",
        _current_agent_id="default",
    )
    return AgentStreamExecutor(
        agent=agent,
        model=SimpleNamespace(model="test-model"),
        system_prompt="",
        tools=[],
        max_turns=3,
        allow_empty_response=allow_empty_response,
    )


def _run_with_silent_model(executor):
    """Run one turn where the model answers nothing at all.

    Context trimming is stubbed out: it needs a real Agent for token
    accounting and has no bearing on empty-response handling.
    """
    with patch.object(executor, "_call_llm_stream", return_value=("", [], "stop")), \
            patch.object(executor, "_trim_messages"), \
            patch.object(executor, "_validate_and_fix_messages"):
        return executor.run_stream("check the price")


class EmptyResponseFallbackTest(unittest.TestCase):
    def test_empty_reply_returned_as_is_when_silence_allowed(self):
        response = _run_with_silent_model(_make_executor(allow_empty_response=True))

        self.assertEqual(response, "")

    def test_empty_reply_gets_fallback_text_for_user_facing_run(self):
        response = _run_with_silent_model(_make_executor(allow_empty_response=False))

        self.assertTrue(response)
        self.assertIn("无法生成回复", response)

    def test_explicit_response_prompt_permits_silence_only_when_allowed(self):
        self.assertIn("返回空", _make_executor(True)._explicit_response_prompt())
        self.assertNotIn("返回空", _make_executor(False)._explicit_response_prompt())


class _AgentBridge:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def agent_reply(self, task_description, **kwargs):
        self.calls.append((task_description, kwargs))
        return SimpleNamespace(content=self.content)


class SchedulerEmptyReplyTest(unittest.TestCase):
    @staticmethod
    def _task():
        return {
            "id": "task-1",
            "action": {
                "type": "agent_task",
                "task_description": "notify me only if the price drops",
                "receiver": "user-1",
                "is_group": False,
                "channel_type": "web",
            },
        }

    def test_empty_reply_sends_nothing_and_does_not_retry(self):
        bridge = _AgentBridge("")

        with patch("channel.channel_factory.create_channel") as create_channel:
            result = _execute_agent_task(self._task(), bridge)

        # True keeps the scheduler from re-running a task that behaved correctly.
        self.assertTrue(result)
        create_channel.assert_not_called()

    def test_non_empty_reply_is_still_delivered(self):
        bridge = _AgentBridge("price dropped to 42")

        with patch("channel.channel_factory.create_channel") as create_channel:
            _execute_agent_task(self._task(), bridge)

        create_channel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
