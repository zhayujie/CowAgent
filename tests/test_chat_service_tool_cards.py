"""When a call's card settles.

A round used to be short enough that settling every card together at the end of
it was indistinguishable from settling each one as it finished. A hand-off holds
the round open for as long as the teammate works, so the difference became the
whole of it: a tool that ran for a second sat unfinished on screen for minutes.
"""
import threading
from types import SimpleNamespace
from typing import ClassVar

import pytest

from agent.chat.service import ChatService


class _ScriptedExecutor:
    """Replays a fixed event sequence, standing in for a turn of an Agent."""

    script: ClassVar[list] = []

    def __init__(self, *, messages, on_event, **kwargs):
        self.messages = list(messages)
        self.on_event = on_event

    def run_stream(self, query):
        for event_type, data in self.script:
            self.on_event({"type": event_type, "data": data})
        return "done"

    def run_start_index(self):
        return None


def _service():
    agent = SimpleNamespace(
        model=SimpleNamespace(),
        tools=[],
        max_steps=4,
        messages=[],
        messages_lock=threading.Lock(),
        workspace_dir=None,
        get_full_system_prompt=lambda: "system",
        _execute_post_process_tools=lambda: None,
    )

    class FakeBridge:
        agent_registry = SimpleNamespace(default_agent_id="primary")
        _resolve_agent_id = staticmethod(lambda agent_id=None: agent_id or "primary")
        _cancel_key = staticmethod(lambda a, t, d: t if a == d else f"{a}::{t}")
        get_agent = staticmethod(lambda session_id=None, agent_id=None: agent)

    service = ChatService(FakeBridge())
    service._build_context = lambda *a, **k: {}
    service._mark_run_active = lambda *a, **k: None
    service._note_evolution_turn = lambda *a, **k: None
    return service


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(
        "agent.protocol.get_cancel_registry",
        lambda: SimpleNamespace(
            register=lambda *a, **k: threading.Event(), unregister=lambda *a, **k: None
        ),
    )
    monkeypatch.setattr(
        "agent.protocol.get_steer_registry",
        lambda: SimpleNamespace(register=lambda *a, **k: [], unregister=lambda *a, **k: None),
    )
    monkeypatch.setattr("agent.protocol.agent_stream.AgentStreamExecutor", _ScriptedExecutor)
    monkeypatch.setattr("config.conf", lambda: {"conversation_persistence": False})


def _hand_off_turn():
    """One hand-off: the teammate runs a tool of its own, then answers."""
    return [
        ("message_end", {"content": "asking", "tool_calls": [{"id": "call_1", "name": "agent_delegate"}]}),
        ("tool_execution_start", {"tool_call_id": "call_1", "tool_name": "agent_delegate",
                                  "arguments": {"agent_id": "dev"}}),
        ("peer_message_start", {"card_id": "call_1", "agent_id": "dev", "agent_name": "Dev"}),
        ("tool_execution_start", {"tool_call_id": "peer_1", "tool_name": "read_file", "arguments": {}}),
        ("tool_execution_end", {"tool_call_id": "peer_1", "tool_name": "read_file",
                                "status": "success", "result": "contents", "execution_time": 1.0}),
        ("message_update", {"delta": "here it is"}),
        ("peer_message_end", {"card_id": "call_1", "agent_id": "dev", "status": "done"}),
        ("tool_execution_end", {"tool_call_id": "call_1", "tool_name": "agent_delegate",
                                "status": "success", "result": "{}", "execution_time": 90.0}),
        ("turn_end", {"turn": 1, "has_tool_calls": True, "tool_count": 1}),
    ]


def _run(script):
    _ScriptedExecutor.script = script
    chunks = []
    _service().run("q", "s1", chunks.append, channel_type="web")
    return chunks


def test_a_call_settles_when_its_own_tool_finishes(runtime):
    chunks = _run(_hand_off_turn())
    order = [c["chunk_type"] for c in chunks]

    # The teammate's call is settled before its turn is even over, rather than
    # waiting on the hand-off that contains it.
    settled = order.index("tool_end")
    assert settled < order.index("peer_end")
    assert order.index("tool_end") < order.index("tool_calls")

    ends = {c["tool_id"]: c for c in chunks if c["chunk_type"] == "tool_end"}
    assert set(ends) == {"peer_1", "call_1"}
    assert ends["peer_1"]["elapsed"] == "1.00s"
    assert ends["peer_1"]["result"] == "contents"
    assert ends["call_1"]["status"] == "success"


def test_every_card_opened_is_settled(runtime):
    chunks = _run(_hand_off_turn())
    opened = {c["tool_id"] for c in chunks if c["chunk_type"] == "tool_start"}
    settled = {c["tool_id"] for c in chunks if c["chunk_type"] == "tool_end"}
    assert opened == settled


def test_the_closing_batch_still_carries_every_result(runtime):
    """A client that predates the per-call chunk learns the outcome as before."""
    chunks = _run(_hand_off_turn())
    batches = [c for c in chunks if c["chunk_type"] == "tool_calls"]
    assert len(batches) == 1
    assert [t["id"] for t in batches[0]["tool_calls"]] == ["peer_1", "call_1"]
