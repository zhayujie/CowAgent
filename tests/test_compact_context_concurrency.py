"""Compacting the history must not swallow a turn that lands while it runs.

``compact_context`` takes ``messages_lock`` twice with a slow LLM summarize
call in between (``agent/protocol/agent.py:903`` -> ``:934`` -> ``:962``). A
turn that arrives during that window writes ``self.messages`` as a whole new
list (``agent.py:869``), so the write-back used to overwrite the user's new
message and the Agent's answer to it -- while still reporting ``ok: True``.

The HTTP route (``POST /api/sessions/<id>/compact_context``) hands over the
live agent from ``peek_agent`` without checking whether a turn is running, and
the console's "compact context" button sits right next to the message box.
"""

import sys
import threading
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.protocol.agent import Agent


def _q(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _a(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


class _SlowFlush:
    """Stands in for the summarize round-trip, deterministically.

    ``entered`` is set once compaction is inside the call -- which is outside
    the lock, the whole point -- and the call does not return until ``release``
    is set. That makes "a turn lands mid-compaction" a fact of the test rather
    than a race.
    """

    def __init__(self, entered, release):
        self.entered = entered
        self.release = release

    def _summarize_messages(self, messages, max_messages=0):
        self.entered.set()
        assert self.release.wait(timeout=5), "summarize was never released"
        return "SUMMARY"

    def _clean_summary_output(self, raw):
        return raw

    def write_daily_summary(self, *args, **kwargs):
        pass


def _agent(history, blocking=False):
    agent = Agent.__new__(Agent)
    agent.messages = list(history)
    agent.messages_lock = threading.RLock()
    agent.last_usage = None
    entered, release = threading.Event(), threading.Event()
    release.set()  # by default the summarize returns at once
    agent.memory_manager = types.SimpleNamespace(
        flush_manager=_SlowFlush(entered, release)
    )
    return agent, (entered, release)


def _run_with_concurrent_write(agent, events, new_messages):
    """Append ``new_messages`` to the history while compaction is summarizing."""
    entered, release = events
    release.clear()

    def worker():
        assert entered.wait(timeout=5), "compaction never reached the summarize step"
        with agent.messages_lock:
            agent.messages = agent.messages + list(new_messages)
        release.set()

    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def _texts(messages):
    out = []
    for message in messages:
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict):
                out.append(block.get("text", ""))
    return out


class CompactContextConcurrencyTest(unittest.TestCase):
    """Three turns, then a fourth that lands mid-compaction."""

    HISTORY = [_q("q1"), _a("a1"), _q("q2"), _a("a2"), _q("q3"), _a("a3")]

    def test_a_turn_that_lands_mid_compaction_is_kept(self):
        agent, events = _agent(self.HISTORY, blocking=True)
        worker = _run_with_concurrent_write(agent, events, [_q("q4"), _a("a4")])
        result = agent.compact_context(keep_recent_turns=1)
        worker.join(timeout=5)

        texts = _texts(agent.messages)
        self.assertTrue(any("q4" in t for t in texts),
                        f"the user's new question was lost: {texts}")
        self.assertTrue(any("a4" in t for t in texts),
                        f"the answer to it was lost: {texts}")
        self.assertTrue(result.get("ok"), result)

    def test_compaction_still_happens_alongside_that_turn(self):
        agent, events = _agent(self.HISTORY, blocking=True)
        worker = _run_with_concurrent_write(agent, events, [_q("q4"), _a("a4")])
        result = agent.compact_context(keep_recent_turns=1)
        worker.join(timeout=5)

        self.assertEqual(result.get("reason"), "compacted")
        self.assertEqual(result.get("compacted_turns"), 2)
        # The summary note is still injected, and q1/q2 are still summarized.
        texts = _texts(agent.messages)
        self.assertTrue(any("SUMMARY" in t for t in texts), texts)
        self.assertFalse(any("q1" in t for t in texts), texts)

    def test_an_untouched_history_compacts_exactly_as_before(self):
        agent, _ = _agent(self.HISTORY)
        result = agent.compact_context(keep_recent_turns=1)

        self.assertEqual(result, {
            "ok": True, "reason": "compacted", "compacted_turns": 2,
            "before": 6, "after": 2,
        })
        texts = _texts(agent.messages)
        self.assertTrue(any("SUMMARY" in t for t in texts), texts)
        self.assertEqual(len(agent.messages), 2)

    def test_nothing_to_compact_is_unchanged(self):
        agent, _ = _agent([_q("q1"), _a("a1")])
        result = agent.compact_context(keep_recent_turns=2)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "nothing_to_compact")
        self.assertEqual(len(agent.messages), 2)

    def test_a_history_rewritten_underneath_is_reported_not_overwritten(self):
        # A concurrent automatic trim replaces the history rather than appending
        # to it. The kept turns no longer describe it, so compaction must decline
        # rather than write a compaction computed from a history that is gone.
        agent, events = _agent(self.HISTORY, blocking=True)
        entered, release = events
        release.clear()

        def concurrent_trim():
            assert entered.wait(timeout=5)
            with agent.messages_lock:
                agent.messages = [_q("trimmed")]
            release.set()

        worker = threading.Thread(target=concurrent_trim)
        worker.start()
        result = agent.compact_context(keep_recent_turns=1)
        worker.join(timeout=5)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "history_changed")
        self.assertEqual(_texts(agent.messages), ["trimmed"])


if __name__ == "__main__":
    unittest.main()