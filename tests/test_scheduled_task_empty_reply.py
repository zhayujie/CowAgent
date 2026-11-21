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
from agent.tools.scheduler.integration import (
    _execute_agent_task,
    _is_empty_scheduled_content,
)
from common import i18n
from tests.test_agent_stream_max_turns import _CountingExecutor


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
    def setUp(self):
        # The fallback text is translated; pin the language so the assertion
        # doesn't depend on the runner's locale (CI defaults to English).
        original = i18n.get_language()
        i18n.set_language("zh")
        self.addCleanup(i18n.set_language, original)

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

    def test_empty_after_tool_turn_still_asks_a_scheduled_run_for_its_answer(self):
        # Silence is allowed for every scheduled task, not only conditional
        # ones: a plain daily summary that ends empty after its tools still has
        # to be asked for the answer, with a prompt that permits returning none.
        executor = _CountingExecutor(
            script=[
                ("", ["fetch_news"]),
                ("", []),
                ("Today's summary.", []),
            ],
            max_turns=5,
            allow_empty_response=True,
        )

        response = executor.run_stream("send me a daily news summary")

        self.assertEqual(response, "Today's summary.")
        self.assertEqual(executor.calls, 3)

    def test_empty_after_tool_turn_still_requests_explicit_reply_for_chat(self):
        executor = _CountingExecutor(
            script=[
                ("", ["check_price"]),
                ("", []),
                ("Price is 105, no drop.", []),
            ],
            max_turns=5,
            allow_empty_response=False,
        )

        response = executor.run_stream("check the price")

        self.assertEqual(response, "Price is 105, no drop.")
        self.assertEqual(executor.calls, 3)

    def test_empty_after_tool_turn_falls_back_when_chat_explicit_retry_stays_empty(self):
        executor = _CountingExecutor(
            script=[
                ("", ["check_price"]),
                ("", []),
                ("", []),
            ],
            max_turns=5,
            allow_empty_response=False,
        )

        response = executor.run_stream("check the price")

        self.assertIn("无法生成回复", response)
        self.assertEqual(executor.calls, 3)

    def test_stream_retries_on_empty_for_user_facing_run(self):
        calls = []

        class _RetryThenAnswerModel:
            model = "test-model"

            def call_stream(self, request):
                calls.append(request)
                if len(calls) == 1:
                    yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}
                else:
                    yield {"choices": [{"delta": {"content": "recovered"}, "finish_reason": "stop"}]}

        agent = SimpleNamespace(
            name="test-agent",
            messages=[],
            tools=[],
            workspace_dir=None,
            last_usage=None,
            _current_session_id="chat-1",
            _current_agent_id="default",
        )
        executor = AgentStreamExecutor(
            agent=agent,
            model=_RetryThenAnswerModel(),
            system_prompt="",
            tools=[],
            max_turns=3,
            allow_empty_response=False,
        )
        with patch.object(executor, "_trim_messages"), \
                patch.object(executor, "_validate_and_fix_messages"):
            response = executor.run_stream("hello")

        self.assertEqual(response, "recovered")
        self.assertEqual(len(calls), 2)


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

    def test_invisible_quote_and_empty_fence_replies_are_suppressed(self):
        empty_variants = [
            "",
            "   \n\t  ",
            '""',
            "''",
            chr(0x201C) + chr(0x201D),
            chr(0x2018) + chr(0x2019),
            '"   "',
            chr(0x200B),
            chr(0x200C) + chr(0x200D) + chr(0x2060),
            f"  {chr(0xFEFF)}  ",
            f'"{chr(0x200B)}"',
            '`""`',
            "```\n```",
            "```text\n   \n```",
            f"```text\n{chr(0x200B)}\n```",
            '```text\n""\n```',
            "```   ```",
            "~~~\n~~~",
        ]
        for payload in empty_variants:
            with self.subTest(payload=repr(payload)):
                self.assertTrue(_is_empty_scheduled_content(payload))
                bridge = _AgentBridge(payload)
                with patch("channel.channel_factory.create_channel") as create_channel:
                    result = _execute_agent_task(self._task(), bridge)
                self.assertTrue(result)
                create_channel.assert_not_called()

    def test_short_real_alerts_are_still_delivered(self):
        real_alerts = [
            "CSL 98.20",
            '"CSL 98.20"',
            "```text\nCSL 98.20\n```",
            "```CSL 98.20```",
            "OK",
            "0",
        ]
        for payload in real_alerts:
            with self.subTest(payload=repr(payload)):
                self.assertFalse(_is_empty_scheduled_content(payload))
                bridge = _AgentBridge(payload)
                with patch("channel.channel_factory.create_channel") as create_channel:
                    result = _execute_agent_task(self._task(), bridge)
                self.assertTrue(result)
                create_channel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
