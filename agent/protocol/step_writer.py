"""
Step writer — persist a run's messages as each step finishes.

A run used to be stored in one batch after it returned, so a long run that
crashed or failed part-way lost every step it had finished. ``StepWriter``
writes the finished steps at each ``turn_end`` instead, then stores whatever
is left once the run returns.

Writing is best-effort: a failure is logged and never reaches the run.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from common.log import logger


class StepWriter:
    """Follows one run and hands its not-yet-stored messages to ``write``.

    Messages are tracked by identity rather than position: the executor edits
    its list in place mid-run (the sanitizer drops or inserts messages before
    each LLM call), so an index would drift and store a message twice or skip
    one.
    """

    def __init__(self, write: Callable[[List[Dict]], None], skip_query: bool = False):
        """
        Args:
            write: Stores a chunk of messages, in order. Called with the live
                message dicts; transform copies, never the dicts themselves.
            skip_query: The run's user message is already stored, so never
                write it again.
        """
        self._write = write
        self._skip_query = skip_query
        self._written_ids: set = set()
        # Holding the dicts keeps their ids from being reused by new ones.
        self._written: List[Dict] = []
        self._started = False
        self._executor = None

    @property
    def started(self) -> bool:
        """Whether this writer has written any message yet."""
        return self._started

    def bind(self, executor) -> None:
        """Attach the executor whose run this writer follows."""
        self._executor = executor

    def step(self) -> None:
        """Write the run's finished steps that are not stored yet.

        A trailing tool_use still waiting for its tool_result is held back to
        the next step, so the store never holds a half-finished tool call.
        """
        try:
            run = self._run_messages()
            if run is None:
                return
            pending = self._pending(run)
            self._commit(pending[:_closed_prefix(pending)])
        except Exception as e:
            logger.warning(f"[StepWriter] Step write skipped: {e}")

    def finish(self, messages: List[Dict]) -> None:
        """Write what is left of the run once it has returned.

        ``messages`` is everything the run added; the steps already stored are
        left out. Nothing is held back here, as with the old one-batch write.
        """
        try:
            self._commit(self._pending(messages or []))
        except Exception as e:
            logger.warning(f"[StepWriter] Final write failed: {e}")

    def _run_messages(self) -> Optional[List[Dict]]:
        executor = self._executor
        run_start_index = getattr(executor, "run_start_index", None)
        if run_start_index is None:
            return None
        start = run_start_index()
        # Compaction replaced the run's query: nothing marks where the run
        # begins, so leave it all to finish().
        if start is None:
            return None
        run = list(executor.messages[start:])
        if self._skip_query and run and id(run[0]) not in self._written_ids:
            self._mark(run[0])
        return run

    def _pending(self, messages: List[Dict]) -> List[Dict]:
        return [
            m for m in messages
            if isinstance(m, dict) and id(m) not in self._written_ids
        ]

    def _commit(self, messages: List[Dict]) -> None:
        if not messages:
            return
        self._write(list(messages))
        self._started = True
        for message in messages:
            self._mark(message)

    def _mark(self, message: Dict) -> None:
        self._written_ids.add(id(message))
        self._written.append(message)


def _closed_prefix(messages: List[Dict]) -> int:
    """Length of the longest prefix with every tool_use answered in it."""
    open_ids: set = set()
    cut = 0
    for i, message in enumerate(messages):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("id"):
                    open_ids.add(block["id"])
                elif block.get("type") == "tool_result":
                    open_ids.discard(block.get("tool_use_id"))
        if not open_ids:
            cut = i + 1
    return cut
