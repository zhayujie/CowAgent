"""Thread-safe active-run steering primitives.

Steering is deliberately separate from the normal per-session message queue.
An instruction is accepted only while exactly one run for the scoped session
is active; idle sessions never start a new run as a side effect.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, List, Optional, Set


class SteerStatus(str, Enum):
    ACCEPTED = "accepted"
    INACTIVE = "inactive"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"
    FULL = "full"
    CLOSING = "closing"


@dataclass(frozen=True)
class SteerResult:
    status: SteerStatus

    @property
    def accepted(self) -> bool:
        return self.status == SteerStatus.ACCEPTED


class SteerInbox:
    """Bounded inbox owned by one active agent run."""

    def __init__(self, max_pending: int = 16, max_chars: int = 8000):
        self.max_pending = max(1, int(max_pending))
        self.max_chars = max(1, int(max_chars))
        self._lock = threading.Lock()
        self._pending: Deque[str] = deque()
        self._accepting = True

    def submit(self, instruction: str) -> SteerResult:
        text = (instruction or "").strip()
        if not text or len(text) > self.max_chars:
            return SteerResult(SteerStatus.INVALID)
        with self._lock:
            if not self._accepting:
                return SteerResult(SteerStatus.CLOSING)
            if len(self._pending) >= self.max_pending:
                return SteerResult(SteerStatus.FULL)
            self._pending.append(text)
        return SteerResult(SteerStatus.ACCEPTED)

    def drain(self) -> List[str]:
        with self._lock:
            items = list(self._pending)
            self._pending.clear()
            return items

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def close_if_empty(self) -> bool:
        """Atomically stop accepting when no instruction is pending.

        This closes the race between a final empty drain and an agent run
        returning: after this method succeeds, submitters receive CLOSING.
        """
        with self._lock:
            if self._pending:
                return False
            self._accepting = False
            return True

    def close(self) -> None:
        with self._lock:
            self._accepting = False


class SteerRegistry:
    """Map a scoped agent/session key to its active run inboxes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_session: Dict[str, Set[SteerInbox]] = {}

    def register(self, session_id: str, inbox: Optional[SteerInbox] = None) -> SteerInbox:
        inbox = inbox or SteerInbox()
        if not session_id:
            return inbox
        with self._lock:
            self._by_session.setdefault(session_id, set()).add(inbox)
        return inbox

    def unregister(self, session_id: str, inbox: Optional[SteerInbox]) -> None:
        if not session_id or inbox is None:
            return
        inbox.close()
        with self._lock:
            bucket = self._by_session.get(session_id)
            if bucket is None:
                return
            bucket.discard(inbox)
            if not bucket:
                self._by_session.pop(session_id, None)

    def submit(self, session_id: str, instruction: str) -> SteerResult:
        if not (instruction or "").strip():
            return SteerResult(SteerStatus.INVALID)
        with self._lock:
            inboxes = list(self._by_session.get(session_id, ()))
        if not inboxes:
            return SteerResult(SteerStatus.INACTIVE)
        if len(inboxes) != 1:
            return SteerResult(SteerStatus.AMBIGUOUS)
        return inboxes[0].submit(instruction)

    def active_count(self, session_id: str) -> int:
        with self._lock:
            return len(self._by_session.get(session_id, ()))


_registry = SteerRegistry()


def get_steer_registry() -> SteerRegistry:
    return _registry
