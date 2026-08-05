"""
Approval data models and thread-safe registry for Human-in-the-loop tool approval.

Provides:
  - ApprovalRequest:  Data model for a pending approval request.
  - ApprovalResult:   Data model for the outcome of an approval decision.
  - ApprovalRegistry: Thread-safe in-process registry keyed by request_id.
  - get_approval_registry(): Module-level singleton accessor.

The design follows the same threading.Event + Lock pattern used by
CancelTokenRegistry in agent/protocol/cancel.py.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ApprovalRequest:
    """A pending approval request for a high-risk tool call.

    Attributes:
        request_id:          Unique identifier for this request.
        tool_name:           Name of the tool requiring approval.
        arguments:           The tool arguments (as a dict).
        risk_level:          Risk level string, e.g. "low", "medium", "high".
        summary:             Human-readable summary of what the tool will do.
        created_at:          Unix timestamp when the request was created.
        event:               threading.Event that the registry waits on.
        decided:             Whether a decision (approve/reject/timeout) has been made.
    """
    request_id: str
    tool_name: str
    arguments: dict
    risk_level: str
    summary: str
    created_at: float = field(default_factory=time.time)
    event: threading.Event = field(default_factory=threading.Event)
    decided: bool = False


@dataclass
class ApprovalResult:
    """The outcome of an approval decision.

    Attributes:
        request_id:  The request this result belongs to.
        approved:    True if the user approved the tool execution.
        reason:      Optional reason provided by the user or system (e.g. timeout).
    """
    request_id: str
    approved: bool
    reason: str = ""


class ApprovalRegistry:
    """In-process thread-safe registry for pending approval requests.

    Thread-safe. Singleton via module-level ``get_approval_registry()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Dict[str, ApprovalRequest] = {}

    def register(self, request: ApprovalRequest) -> str:
        """Register a new approval request and return its request_id."""
        with self._lock:
            self._requests[request.request_id] = request
        return request.request_id

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Look up a pending request by ID. Returns None if not found."""
        with self._lock:
            return self._requests.get(request_id)

    def approve(self, request_id: str, reason: str = "") -> bool:
        """Approve a pending request. Returns True when the request was found."""
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                return False
            request.decided = True
            request._result = ApprovalResult(
                request_id=request_id, approved=True, reason=reason,
            )
        request.event.set()
        return True

    def reject(self, request_id: str, reason: str = "") -> bool:
        """Reject a pending request. Returns True when the request was found."""
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                return False
            request.decided = True
            request._result = ApprovalResult(
                request_id=request_id, approved=False, reason=reason,
            )
        request.event.set()
        return True

    def wait_for_decision(self, request_id: str, timeout: float = 30.0) -> ApprovalResult:
        """Block the calling thread until a decision is made or the timeout expires.

        Returns:
            ApprovalResult with approved=True/False.
            When the timeout expires, ``approved`` is False and ``reason`` is "timeout".
        """
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                return ApprovalResult(
                    request_id=request_id,
                    approved=False,
                    reason="request not found",
                )
            event = request.event

        # Wait for the event to be signalled (approve/reject) or timeout
        triggered = event.wait(timeout=timeout)

        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                return ApprovalResult(
                    request_id=request_id,
                    approved=False,
                    reason="request not found",
                )
            if not triggered:
                # Timeout — auto-reject
                request.decided = True
                return ApprovalResult(
                    request_id=request_id,
                    approved=False,
                    reason="timeout",
                )
            # Decision was made — read the stored result from approve/reject
            result = getattr(request, "_result", None)
            if result is not None:
                return result
            # Fallback (shouldn't happen in normal flow)
            return ApprovalResult(
                request_id=request_id,
                approved=False,
                reason="unknown",
            )

    def unregister(self, request_id: str) -> None:
        """Remove a request from the registry once the decision has been consumed."""
        with self._lock:
            self._requests.pop(request_id, None)


_registry = None
_registry_lock = threading.Lock()


def get_approval_registry() -> ApprovalRegistry:
    """Module-level accessor for the singleton ApprovalRegistry."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ApprovalRegistry()
    return _registry