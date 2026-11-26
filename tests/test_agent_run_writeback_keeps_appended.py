"""A run's write-back keeps messages appended to the history while it ran.

Agent.run_stream (channels, through AgentBridge.agent_reply) and ChatService.run
(cloud client, OpenAI-compatible API) give the
executor a copy of ``agent.messages`` and, when the run ends, replace
``agent.messages`` with the executor's list. Anything appended to
``agent.messages`` in between was dropped.

AgentBridge.remember_scheduled_output appends exactly like that: a scheduled
task delivers its output to the receiver's chat and adds the visible pair to
that session's cached agent, so the user can ask about it next. When the user
is in the middle of a turn at that moment, the pair is gone from the agent's
context once the turn ends, although it is stored and shown in the chat.
"""

import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent import Agent  # noqa: E402
from bridge.agent_bridge import AgentBridge  # noqa: E402


def _q(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _a(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _texts(messages):
    return [block.get("text", "") for m in messages for block in m["content"]]


def _receiver_bridge(agent):
    """An AgentBridge with storage stubbed out; only the in-memory part runs."""
    bridge = AgentBridge.__new__(AgentBridge)
    bridge._persist_messages = lambda *args, **kwargs: True
    bridge.get_conversation_store = lambda agent_id=None: SimpleNamespace(
        prune_scheduled_messages=lambda *args, **kwargs: 0
    )
    bridge.get_cached_agent = lambda session_id, agent_id=None: agent
    return bridge


class _ExecutorWithDelivery:
    """Stands in for AgentStreamExecutor: answers after ``during_run`` ran."""

    during_run = None

    def __init__(self, *, messages, **kwargs):
        self.messages = messages

    def run_stream(self, user_message):
        self.messages.append(_q(user_message))
        type(self).during_run()
        self.messages.append(_a("answer"))
        return "answer"

    def run_start_index(self):
        return len(self.messages) - 2


def _agent(history):
    agent = Agent(system_prompt="", model=SimpleNamespace(model="test"), enable_skills=False)
    agent.messages = list(history)
    agent.get_full_system_prompt = lambda skill_filter=None: ""
    return agent


def test_scheduled_output_delivered_mid_run_stays_in_context():
    agent = _agent([_q("q1"), _a("a1")])
    bridge = _receiver_bridge(agent)

    def deliver():
        # The scheduler runs on its own thread while the user's turn is busy.
        worker = threading.Thread(
            target=bridge.remember_scheduled_output,
            args=("s1", "Reminder: stand-up in 10 minutes"),
            kwargs={"task_description": "stand-up reminder"},
        )
        worker.start()
        worker.join(timeout=5)

    _ExecutorWithDelivery.during_run = staticmethod(deliver)
    with patch("agent.protocol.agent.AgentStreamExecutor", _ExecutorWithDelivery):
        assert agent.run_stream("q2") == "answer"

    texts = _texts(agent.messages)
    assert "Reminder: stand-up in 10 minutes" in texts, texts
    assert texts[:4] == ["q1", "a1", "q2", "answer"], texts
    # Only the run's own messages are new for the bridge to persist; the
    # scheduled pair was stored by remember_scheduled_output itself.
    assert _texts(agent._last_run_new_messages) == ["q2", "answer"]


def test_run_without_concurrent_writes_is_unchanged():
    agent = _agent([_q("q1"), _a("a1")])
    _ExecutorWithDelivery.during_run = staticmethod(lambda: None)
    with patch("agent.protocol.agent.AgentStreamExecutor", _ExecutorWithDelivery):
        agent.run_stream("q2")

    assert _texts(agent.messages) == ["q1", "a1", "q2", "answer"]


def test_merge_appends_what_arrived_after_the_run():
    from agent.protocol.message_utils import merge_run_history

    base = [_q("q1"), _a("a1")]
    arrived = [_q("[SCHEDULED] t"), _a("out")]
    current = base + arrived
    run = base + [_q("q2"), _a("a2")]

    merged = merge_run_history(base, current, run)

    assert _texts(merged) == ["q1", "a1", "q2", "a2", "[SCHEDULED] t", "out"]


def test_merge_keeps_the_run_when_history_was_not_appended_to():
    from agent.protocol.message_utils import merge_run_history

    base = [_q("q1"), _a("a1")]
    run = [_q("q1"), _a("a1"), _q("q2"), _a("a2")]

    # Untouched history.
    assert merge_run_history(base, list(base), run) == run
    # A rewrite (a sync from the store builds new message dicts) is not an
    # append, so the run's own history wins as before.
    rewritten = [_q("q1"), _a("a1"), _q("x")]
    assert merge_run_history(base, rewritten, run) == run


def test_merge_keeps_appends_after_the_run_trimmed_its_history():
    from agent.protocol.message_utils import merge_run_history

    base = [_q("q1"), _a("a1"), _q("q2"), _a("a2")]
    arrived = [_q("[SCHEDULED] t"), _a("out")]
    trimmed_run = [base[2], base[3], _q("q3"), _a("a3")]

    merged = merge_run_history(base, base + arrived, trimmed_run)

    assert _texts(merged) == ["q2", "a2", "q3", "a3", "[SCHEDULED] t", "out"]


def test_chat_service_run_keeps_scheduled_output_delivered_mid_run(monkeypatch):
    """ChatService.run has its own copy of the write-back."""
    from agent.chat.service import ChatService

    agent = SimpleNamespace(
        model=SimpleNamespace(),
        tools=[],
        max_steps=1,
        messages=[_q("q1"), _a("a1")],
        messages_lock=threading.Lock(),
        workspace_dir=None,
        get_full_system_prompt=lambda: "system",
        _execute_post_process_tools=lambda: None,
    )
    bridge = _receiver_bridge(agent)

    class FakeBridge:
        agent_registry = SimpleNamespace(default_agent_id="primary")

        @staticmethod
        def _resolve_agent_id(agent_id=None):
            return agent_id or "primary"

        @staticmethod
        def _cancel_key(agent_id, token, default_agent_id):
            return token

        @staticmethod
        def get_agent(session_id=None, agent_id=None):
            return agent

    service = ChatService(FakeBridge())
    service._build_context = lambda *args, **kwargs: {}
    service._mark_run_active = lambda *args, **kwargs: None
    service._note_evolution_turn = lambda *args, **kwargs: None

    def deliver():
        bridge.remember_scheduled_output("s1", "Reminder: stand-up in 10 minutes")

    _ExecutorWithDelivery.during_run = staticmethod(deliver)
    monkeypatch.setattr("agent.protocol.agent_stream.AgentStreamExecutor", _ExecutorWithDelivery)
    monkeypatch.setattr("config.conf", lambda: {"conversation_persistence": False})

    service.run("q2", "s1", lambda chunk: None)

    texts = _texts(agent.messages)
    assert texts[:4] == ["q1", "a1", "q2", "answer"], texts
    assert "Reminder: stand-up in 10 minutes" in texts, texts
