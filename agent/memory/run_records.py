"""Opening and closing a task record around one agent run.

Three rules shape this module:

1. **Recording must never take the run down with it.** A trace exists to explain
   what happened; one that can fail the thing it describes is worse than none.
   Every write is wrapped, and a failure is logged and dropped. ``open_run``
   always returns a usable record, inert when the store is unreachable, so no
   call site needs a None check.
2. **The run id comes from the ambient identity, so nesting is automatic.** A
   sub agent runs inside its parent's scope and therefore sees the parent's run
   as its ``parent_run_id`` without anyone passing anything down. That is what
   makes the tree buildable.
3. **Opening the record and entering its scope are separate steps.** A turn
   persists the user's question before the agent starts and the reply after it
   finishes, so the record has to exist earlier than the scope does. Callers
   that need neither split use ``record_run``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from agent.memory.conversation_store import new_run_id
from common.log import logger
from common.runtime_identity import current_identity, identity_scope


_RESOLVE = object()


def _goal_from(user_message: str) -> str:
    """One line for the list column. Raw input runs to hundreds of characters
    often enough that showing it verbatim makes a list unreadable."""
    text = (user_message or "").strip()
    if not text:
        return ""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first[:200]


def summarize_messages(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Steps and sub agent count, read off the messages a run produced.

    Derived afterwards rather than counted as it goes, so the executor needs no
    new state and a run that dies partway still reports what it managed to do.
    """
    steps = 0
    subagents = 0
    for message in messages or []:
        if message.get("role") != "assistant":
            continue
        steps += 1
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "subagent":
                continue
            tasks = (block.get("input") or {}).get("tasks")
            subagents += len(tasks) if isinstance(tasks, list) and tasks else 1
    return {"steps": steps, "subagents": subagents}


class RunRecord:
    """An opened run. Inert when ``store`` is None, so callers can use it
    unconditionally."""

    def __init__(self, run_id: str, store, parent_run_id: str = ""):
        self.run_id = run_id
        self.parent_run_id = parent_run_id
        self._store = store
        self._lock = threading.Lock()
        self._closed = False

    def scope(self):
        """Put this run in scope, so work underneath is attributable to it and
        a sub agent spawned inside nests under it."""
        return identity_scope(run_id=self.run_id)

    def close(
        self,
        *,
        status: str = "done",
        steps: int = 0,
        subagents: int = 0,
        error: str = "",
        extras: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Idempotent, so a caller may close explicitly with real numbers even
        when something else would close it on the way out."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._store is None:
            return
        try:
            self._store.finish_run(
                self.run_id,
                status=status,
                steps=steps,
                subagents=subagents,
                error=error,
                extras=extras,
            )
        except Exception as e:
            logger.debug(f"[RunRecord] closing {self.run_id} failed: {e}")


def open_run(
    user_message: str,
    *,
    trigger_type: str = "message",
    channel_type: str = "",
    model: str = "",
    store=_RESOLVE,
) -> RunRecord:
    """Write the index row and return the record. Never raises.

    Omitting ``store`` resolves one from the ambient identity. Passing None says
    "do not record this", which is different: a caller that knows which database
    it wants and could not get it must not silently land in the default one.
    """
    identity = current_identity()
    run_id = new_run_id()
    parent_run_id = identity.run_id or ""

    if store is _RESOLVE:
        try:
            from agent.memory import get_conversation_store

            store = get_conversation_store()
        except Exception as e:
            logger.debug(f"[RunRecord] no store for {run_id}: {e}")
            store = None

    if store is None:
        return RunRecord(run_id, None, parent_run_id)

    try:
        store.start_run(
            run_id,
            parent_run_id=parent_run_id,
            agent_id=identity.agent_id or "",
            user_id=identity.user_id or "",
            session_id=identity.session_id or "",
            channel_type=channel_type,
            trigger_type=trigger_type,
            goal=_goal_from(user_message),
            model=model,
        )
    except Exception as e:
        logger.debug(f"[RunRecord] opening {run_id} failed: {e}")
        return RunRecord(run_id, None, parent_run_id)

    return RunRecord(run_id, store, parent_run_id)


@contextmanager
def record_run(user_message: str, **kwargs):
    """Open a run, keep it in scope for the block, close it on the way out.

    For callers whose whole turn is the block: sub agents and self-evolution. A
    turn that persists around the run wants ``open_run`` plus ``scope``.
    """
    record = open_run(user_message, **kwargs)
    with record.scope():
        try:
            yield record
        except BaseException as e:
            record.close(status="failed", error=f"{type(e).__name__}: {e}")
            raise
        else:
            record.close()
