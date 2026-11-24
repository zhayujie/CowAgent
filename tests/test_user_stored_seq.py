"""The seq of a question is announced once it is stored, so a turn stopped or
failed before its `done` can still be retried and edited."""

import threading
from types import SimpleNamespace

import pytest

from agent.memory.conversation_store import ConversationStore
from bridge.agent_bridge import AgentBridge
from channel.web import web_channel


WebChannel = dict(zip(
    web_channel.WebChannel.__code__.co_freevars,
    (cell.cell_contents for cell in web_channel.WebChannel.__closure__),
))["cls"]


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "history.db")


def test_the_seq_read_back_is_the_question_just_stored(store, monkeypatch):
    store.append_messages("s1", [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        {"role": "assistant", "content": "a1"},
    ])
    bridge = AgentBridge.__new__(AgentBridge)
    monkeypatch.setattr(bridge, "get_conversation_store", lambda agent_id=None: store, raising=False)

    assert bridge._pre_persist_user_message("s1", "q2", {}, False)
    assert bridge._latest_user_seq("s1") == 4


def test_the_web_stream_carries_it(monkeypatch):
    channel = SimpleNamespace(
        sse_streams={"req": web_channel.SSEStreamState()},
        _sse_streams_lock=threading.RLock(),
        SSE_REPLAY_MAX_EVENTS=5000,
        SSE_REPLAY_MAX_BYTES=4 * 1024 * 1024,
    )
    channel._publish_sse_event = lambda rid, event: WebChannel._publish_sse_event(channel, rid, event)
    on_event = WebChannel._make_sse_callback(channel, "req")

    on_event({"type": "user_stored", "data": {"user_seq": 4}})

    [(item, _)] = channel.sse_streams["req"].events
    assert item["type"] == "user_stored"
    assert item["user_seq"] == 4
