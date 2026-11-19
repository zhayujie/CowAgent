# encoding:utf-8
"""The injected explicit-response prompt must never survive into history.

After a tool turn, an empty LLM reply triggers a synthetic user prompt
("tell the user what the tools did…") and one more model call. The removal
of that prompt lived on the happy path only: when the extra call raised
(retries exhausted, auth error, user cancel), the prompt stayed in
``executor.messages`` and was persisted by the caller as if the user had
typed it — replayed on reload and extracted into memory summaries.

The twin max-turns path pops its summary prompt in a ``finally``
(test_agent_stream_max_turns.py); this pins the same guarantee for the
empty-reply path.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_agent_stream_max_turns import _CountingExecutor

RAISE = ("__raise__", [])


class _RaisingCountingExecutor(_CountingExecutor):
    """Like the counting executor, but a scripted RAISE entry makes the next
    model call fail — the way a real provider error or cancel would."""

    def _call_llm_stream(self, retry_on_empty=True):
        text, names = self.script[0]
        if text == RAISE[0]:
            self.script.pop(0)
            self.calls += 1
            raise RuntimeError("provider 401")
        return super()._call_llm_stream(retry_on_empty)


class EmptyReplyPromptLeakTest(unittest.TestCase):

    def test_the_prompt_is_removed_when_the_extra_call_raises(self):
        # Turn 1: a tool call. Turn 2: empty reply -> prompt injected -> the
        # extra call dies the way a real provider failure does.
        executor = _RaisingCountingExecutor(
            script=[("", ["one"]), ("", []), RAISE],
            max_turns=5,
        )

        # The provider failure propagates to the caller (which is what
        # persists executor.messages) — the leak happened exactly there.
        with self.assertRaises(RuntimeError):
            executor.run_stream("do the thing")

        prompt_snippet = executor._explicit_response_prompt()[:24]
        leaked = [
            m for m in executor.agent.messages
            if m.get("role") == "user"
            and any(prompt_snippet in (b.get("text") or "")
                    for b in m.get("content", []) if isinstance(b, dict))
        ]
        self.assertEqual(leaked, [], "synthetic prompt survived a failed extra call")

    def test_the_prompt_is_removed_on_the_happy_path_too(self):
        # The pre-existing behaviour: the extra call answers, prompt removed.
        executor = _CountingExecutor(
            script=[("", ["one"]), ("", []), ("the answer", [])],
            max_turns=5,
        )

        response = executor.run_stream("do the thing")

        self.assertEqual(response, "the answer")
        prompt_snippet = executor._explicit_response_prompt()[:24]
        leaked = [
            m for m in executor.agent.messages
            if m.get("role") == "user"
            and any(prompt_snippet in (b.get("text") or "")
                    for b in m.get("content", []) if isinstance(b, dict))
        ]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
