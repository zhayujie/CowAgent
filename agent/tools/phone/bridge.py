"""The hand-off between phone tools and the app that hosts this kernel.

The kernel cannot reach the phone's location, dialer or other apps; the app
can. A tool call becomes a request that the app picks up by long-polling
``/api/phone/poll``, carries out (asking the user where it has to) and answers
on ``/api/phone/requests/<id>``. Nothing is known until the app first polls,
so a kernel without it (web, desktop, a server) never offers these tools.
"""

import threading
import time
import uuid
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

POLL_WAIT_MAX = 25.0

# How long a request waits for the app to pick it up. Polls pause for a moment
# whenever the app leaves the screen, a system dialog included, and resume
# when it is back.
DELIVERY_WAIT = 15.0


class PhoneBridge:
    def __init__(self):
        self._cond = threading.Condition()
        self._capabilities: frozenset = frozenset()
        self._queue: deque = deque()
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._cancelled: List[str] = []

    def supports(self, capability: str) -> bool:
        return capability in self._capabilities

    def call(self, tool: str, args: Dict[str, Any], *, timeout: float,
             cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
        """Have the app run ``tool`` and wait for its answer.

        Always returns ``{"ok": bool, "result"?: Any, "error"?: str, "message"?: str}``;
        ``error`` is ``app_inactive``, ``timeout`` or ``cancelled`` when the app
        never answered.
        """
        rid = "r_" + uuid.uuid4().hex[:16]
        entry: Dict[str, Any] = {"done": threading.Event(), "answer": None}
        request = {"id": rid, "tool": tool, "args": args}
        with self._cond:
            self._pending[rid] = entry
            self._queue.append(request)
            self._cond.notify_all()

        start = time.monotonic()
        outcome = None
        while not entry["done"].wait(0.25):
            if cancel_event is not None and cancel_event.is_set():
                outcome = "cancelled"
                break
            waited = time.monotonic() - start
            if waited >= timeout:
                outcome = "timeout"
                break
            if waited >= DELIVERY_WAIT:
                with self._cond:
                    if request in self._queue:
                        outcome = "app_inactive"
                        break

        with self._cond:
            self._pending.pop(rid, None)
            if entry["done"].is_set():
                return entry["answer"]
            if request in self._queue:
                self._queue.remove(request)
            else:
                # Already with the app, which may be showing a prompt for it.
                self._cancelled.append(rid)
                self._cond.notify_all()
        return {"ok": False, "error": outcome}

    def poll(self, capabilities: Iterable[str], wait: float) -> Tuple[List[dict], List[str]]:
        """Requests for the app, waiting up to ``wait`` seconds for the first one."""
        wait = max(0.0, min(float(wait), POLL_WAIT_MAX))
        with self._cond:
            self._capabilities = frozenset(capabilities)
            end = time.monotonic() + wait
            while not self._queue and not self._cancelled:
                left = end - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            requests = list(self._queue)
            self._queue.clear()
            cancelled = self._cancelled
            self._cancelled = []
        return requests, cancelled

    def answer(self, rid: str, answer: Dict[str, Any]) -> bool:
        """Deliver the app's answer; False when nobody waits for it any more."""
        with self._cond:
            entry = self._pending.get(rid)
            if entry is None:
                return False
            entry["answer"] = answer
            entry["done"].set()
            return True


bridge = PhoneBridge()
