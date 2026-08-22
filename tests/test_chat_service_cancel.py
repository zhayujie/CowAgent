import threading
from types import SimpleNamespace
from typing import ClassVar

import pytest

from agent.chat.service import ChatService


class _RecordingCancelRegistry:
    def __init__(self):
        self.calls = []
        self.events = {}

    def register(self, request_id, session_id=None):
        self.calls.append(("register", request_id, session_id))
        event = self.events.get(request_id)
        if event is None:
            event = threading.Event()
            self.events[request_id] = event
        return event

    def unregister(self, request_id):
        self.calls.append(("unregister", request_id))
        self.events.pop(request_id, None)


class _RecordingSteerRegistry:
    def register(self, session_id):
        return []

    def unregister(self, session_id, inbox):
        return None


class _FakeExecutor:
    instances: ClassVar[list] = []
    run_queries: ClassVar[list] = []

    def __init__(self, *, messages, cancel_event, **kwargs):
        self.messages = list(messages)
        self.cancel_event = cancel_event
        self.__class__.instances.append(self)

    def run_stream(self, query):
        self.__class__.run_queries.append(query)
        self.messages.append({"role": "user", "content": query})
        return ""


def _service():
    agent = SimpleNamespace(
        model=SimpleNamespace(),
        tools=[],
        max_steps=1,
        messages=[],
        messages_lock=threading.Lock(),
        workspace_dir=None,
        get_full_system_prompt=lambda: "system",
        _execute_post_process_tools=lambda: None,
    )

    class FakeBridge:
        agent_registry = SimpleNamespace(default_agent_id="primary")

        @staticmethod
        def _resolve_agent_id(agent_id=None):
            return agent_id or "primary"

        @staticmethod
        def _cancel_key(agent_id, token, default_agent_id):
            return token if agent_id == default_agent_id else f"{agent_id}::{token}"

        @staticmethod
        def get_agent(session_id=None, agent_id=None):
            return agent

    service = ChatService(FakeBridge())
    service._build_context = lambda *args, **kwargs: {}
    service._mark_run_active = lambda *args, **kwargs: None
    service._note_evolution_turn = lambda *args, **kwargs: None
    return service


@pytest.fixture
def cancel_runtime(monkeypatch):
    cancel_registry = _RecordingCancelRegistry()
    _FakeExecutor.instances = []
    _FakeExecutor.run_queries = []
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: cancel_registry)
    monkeypatch.setattr(
        "agent.protocol.get_steer_registry", lambda: _RecordingSteerRegistry()
    )
    monkeypatch.setattr(
        "agent.protocol.agent_stream.AgentStreamExecutor", _FakeExecutor
    )
    monkeypatch.setattr("config.conf", lambda: {"conversation_persistence": False})
    return cancel_registry


def test_run_registers_and_unregisters_per_request_cancel_key(cancel_runtime):
    service = _service()

    service.run(
        "hello",
        "session-1",
        lambda chunk: None,
        agent_id="research",
        request_id="request-1",
    )

    assert cancel_runtime.calls == [
        ("register", "research::request-1", "research::session-1"),
        ("unregister", "research::request-1"),
    ]
    assert _FakeExecutor.instances[0].cancel_event is not None


def test_run_without_request_id_remains_session_scoped(cancel_runtime):
    service = _service()

    service.run(
        "hello",
        "session-1",
        lambda chunk: None,
        agent_id="research",
    )

    assert cancel_runtime.calls == [
        ("register", "research::session-1", "research::session-1"),
        ("unregister", "research::session-1"),
    ]


def test_run_reuses_pre_cancelled_event_without_executing_or_writing_history(
    cancel_runtime,
):
    service = _service()
    cancel_event = cancel_runtime.register(
        "research::request-1", session_id="research::session-1"
    )
    cancel_event.set()
    cancel_runtime.calls.clear()

    service.run(
        "hello",
        "session-1",
        lambda chunk: None,
        agent_id="research",
        request_id="request-1",
    )

    assert cancel_runtime.calls == [
        ("register", "research::request-1", "research::session-1"),
        ("unregister", "research::request-1"),
    ]
    assert _FakeExecutor.instances[0].cancel_event is cancel_event
    assert _FakeExecutor.run_queries == []
    assert _FakeExecutor.instances[0].messages == []
