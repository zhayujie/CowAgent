"""
Tests for the Human-in-the-loop approval mechanism (agent/protocol/approval.py).

Covers:
  - Happy path: register → approve → wait_for_decision returns approved=True
  - Reject path: register → reject → wait_for_decision returns approved=False
  - Timeout path: register → wait_for_decision (no decision) → auto-reject
  - Request not found: wait_for_decision on unknown request_id
  - Singleton: get_approval_registry() returns the same instance
"""

import threading
import time
from unittest.mock import Mock, patch

from agent.protocol.approval import (
    ApprovalRequest,
    ApprovalResult,
    ApprovalRegistry,
    get_approval_registry,
)


def test_approve_happy_path():
    """Register a request, approve it, verify wait_for_decision returns approved=True."""
    registry = ApprovalRegistry()
    req = ApprovalRequest(
        request_id="test-001",
        tool_name="write",
        arguments={"path": "/tmp/test.txt", "content": "hello"},
        risk_level="high",
        summary="write(path=/tmp/test.txt, content=hello)",
    )
    registry.register(req)

    # Approve in a separate thread (simulating user decision)
    def _do_approve():
        time.sleep(0.05)
        registry.approve("test-001", reason="user confirmed")

    t = threading.Thread(target=_do_approve, daemon=True)
    t.start()

    result = registry.wait_for_decision("test-001", timeout=5.0)
    assert result.approved is True, f"Expected approved=True, got {result}"
    assert result.request_id == "test-001"
    assert result.reason == "user confirmed"

    registry.unregister("test-001")
    assert registry.get_request("test-001") is None


def test_reject_path():
    """Register a request, reject it, verify wait_for_decision returns approved=False."""
    registry = ApprovalRegistry()
    req = ApprovalRequest(
        request_id="test-002",
        tool_name="bash",
        arguments={"command": "rm -rf /"},
        risk_level="high",
        summary="bash(command=rm -rf /)",
    )
    registry.register(req)

    def _do_reject():
        time.sleep(0.05)
        registry.reject("test-002", reason="user denied")

    t = threading.Thread(target=_do_reject, daemon=True)
    t.start()

    result = registry.wait_for_decision("test-002", timeout=5.0)
    assert result.approved is False, f"Expected approved=False, got {result}"
    assert result.reason == "user denied"

    registry.unregister("test-002")


def test_timeout_auto_reject():
    """Register a request, never decide, verify timeout returns approved=False."""
    registry = ApprovalRegistry()
    req = ApprovalRequest(
        request_id="test-003",
        tool_name="edit",
        arguments={"path": "/tmp/test.txt", "oldText": "foo", "newText": "bar"},
        risk_level="high",
        summary="edit(path=/tmp/test.txt)",
    )
    registry.register(req)

    # Use a very short timeout to test the timeout path
    result = registry.wait_for_decision("test-003", timeout=0.1)
    assert result.approved is False, f"Expected approved=False (timeout), got {result}"
    assert result.reason == "timeout"

    registry.unregister("test-003")


def test_request_not_found():
    """wait_for_decision on an unknown request_id returns approved=False."""
    registry = ApprovalRegistry()
    result = registry.wait_for_decision("nonexistent", timeout=0.1)
    assert result.approved is False
    assert result.reason == "request not found"


def test_approve_nonexistent():
    """approve() on an unknown request_id returns False."""
    registry = ApprovalRegistry()
    assert registry.approve("nonexistent") is False


def test_reject_nonexistent():
    """reject() on an unknown request_id returns False."""
    registry = ApprovalRegistry()
    assert registry.reject("nonexistent") is False


def test_get_request():
    """get_request() returns the request or None."""
    registry = ApprovalRegistry()
    assert registry.get_request("nonexistent") is None

    req = ApprovalRequest(
        request_id="test-004",
        tool_name="send",
        arguments={"path": "/tmp/file.pdf"},
        risk_level="medium",
        summary="send(path=/tmp/file.pdf)",
    )
    registry.register(req)
    assert registry.get_request("test-004") is req
    assert registry.get_request("test-004").tool_name == "send"

    registry.unregister("test-004")
    assert registry.get_request("test-004") is None


def test_singleton():
    """get_approval_registry() always returns the same instance."""
    r1 = get_approval_registry()
    r2 = get_approval_registry()
    assert r1 is r2


def test_concurrent_approve_reject():
    """Multiple threads waiting on the same request are all unblocked."""
    registry = ApprovalRegistry()
    req = ApprovalRequest(
        request_id="test-005",
        tool_name="write",
        arguments={"path": "/tmp/test.txt", "content": "data"},
        risk_level="high",
        summary="write(...)",
    )
    registry.register(req)

    results = []

    def _wait():
        r = registry.wait_for_decision("test-005", timeout=5.0)
        results.append(r)

    threads = [threading.Thread(target=_wait, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()

    time.sleep(0.05)
    registry.approve("test-005", reason="bulk approve")

    for t in threads:
        t.join(timeout=1.0)

    assert len(results) == 3
    for r in results:
        assert r.approved is True

    registry.unregister("test-005")


def test_double_approve_is_idempotent():
    """Calling approve() twice on the same request doesn't crash."""
    registry = ApprovalRegistry()
    req = ApprovalRequest(
        request_id="test-006",
        tool_name="write",
        arguments={},
        risk_level="high",
        summary="test",
    )
    registry.register(req)

    def _approve_twice():
        time.sleep(0.05)
        registry.approve("test-006")
        # Second call should be safe (event.set() is idempotent)
        registry.approve("test-006")

    t = threading.Thread(target=_approve_twice, daemon=True)
    t.start()

    result = registry.wait_for_decision("test-006", timeout=5.0)
    assert result.approved is True

    registry.unregister("test-006")


def test_register_after_unregister():
    """Re-registering a request with the same ID after unregister works."""
    registry = ApprovalRegistry()
    req1 = ApprovalRequest(
        request_id="test-007",
        tool_name="write",
        arguments={},
        risk_level="high",
        summary="first",
    )
    registry.register(req1)
    registry.unregister("test-007")

    req2 = ApprovalRequest(
        request_id="test-007",
        tool_name="bash",
        arguments={},
        risk_level="high",
        summary="second",
    )
    registry.register(req2)
    assert registry.get_request("test-007").tool_name == "bash"
    registry.unregister("test-007")


def test_approval_event_emitted_by_executor():
    """Verify that _check_tool_approval emits the tool_approval_required event
    when the tool requires approval and the config flag is enabled."""
    from agent.protocol.agent_stream import AgentStreamExecutor
    from types import SimpleNamespace

    events = []

    def on_event(event):
        events.append(event)

    executor = AgentStreamExecutor(
        agent=SimpleNamespace(),
        model=SimpleNamespace(model="test-model"),
        system_prompt="",
        tools=[],
        max_turns=1,
        on_event=on_event,
        messages=[],
    )

    # Mock a tool that requires approval
    mock_tool = SimpleNamespace(
        name="write",
        requires_approval=True,
        risk_level="high",
    )

    with patch("config.conf") as mock_conf:
        mock_conf.return_value.get.return_value = True  # tool_approval_enabled

        result = executor._check_tool_approval(
            mock_tool,
            tool_id="call_123",
            arguments={"path": "/tmp/test.txt", "content": "hello"},
        )

    # Since there's no one to approve, it will timeout after 30s.
    # We use a very short timeout to check that the event was emitted.
    # Actually _check_tool_approval uses a hardcoded timeout of 30s.
    # Let's just verify the event was emitted before timeout.
    approval_events = [e for e in events if e.get("type") == "tool_approval_required"]
    # The event should have been emitted
    assert len(approval_events) >= 1, f"No approval events emitted: {events}"

    # We can't easily test the full flow here without waiting 30s,
    # so we just verify the event emission works.
    event_data = approval_events[0].get("data", {})
    assert event_data.get("tool_name") == "write"
    assert event_data.get("risk_level") == "high"


if __name__ == "__main__":
    # Run tests manually (excludes the event emission test which requires a 30s timeout)
    test_approve_happy_path()
    print("✓ test_approve_happy_path")

    test_reject_path()
    print("✓ test_reject_path")

    test_timeout_auto_reject()
    print("✓ test_timeout_auto_reject")

    test_request_not_found()
    print("✓ test_request_not_found")

    test_approve_nonexistent()
    print("✓ test_approve_nonexistent")

    test_reject_nonexistent()
    print("✓ test_reject_nonexistent")

    test_get_request()
    print("✓ test_get_request")

    test_singleton()
    print("✓ test_singleton")

    test_concurrent_approve_reject()
    print("✓ test_concurrent_approve_reject")

    test_double_approve_is_idempotent()
    print("✓ test_double_approve_is_idempotent")

    test_register_after_unregister()
    print("✓ test_register_after_unregister")

    print("\n✅ All tests passed!")