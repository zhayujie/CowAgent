"""Unrelated Chat API sessions must not wait on each other's agent run.

The session lock used to be one of 64 shared stripes picked by
``hash((agent, session)) % 64``. Two unrelated conversations (or two
stateless requests) that landed on the same stripe queued behind each
other for a whole agent run, and a streaming request stuck there was
answered ``500 timeout`` once its first-event budget ran out.
"""

import gc
import threading

import pytest

from channel.web.api import openai_compat
from channel.web.api.openai_compat import handle_chat_completions


_CATALOG = [{"id": "deepseek", "label": "DeepSeek", "models": ["deepseek-chat"]}]
_OLD_STRIPES = 64


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    from agent.protocol.cancel import CancelTokenRegistry

    registry = CancelTokenRegistry()
    monkeypatch.setattr(openai_compat, "_model_catalog", lambda: _CATALOG)
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)
    monkeypatch.setattr(
        openai_compat,
        "_request_cancel_scope",
        lambda request_id, session_id=None, agent_id=None: (request_id, session_id),
    )
    monkeypatch.setattr(openai_compat, "_cancel_agent_request", lambda *args: False)
    monkeypatch.setattr(openai_compat, "_FIRST_EVENT_TIMEOUT_SECONDS", 2)


def _same_old_stripe(session_for):
    """Two distinct keys whose sessions shared a stripe under the old scheme."""
    owner = openai_compat._agent_registry().default_agent_id
    seen = {}
    for i in range(_OLD_STRIPES + 1):
        key = f"k{i}"
        stripe = hash((owner, session_for(key))) % _OLD_STRIPES
        if stripe in seen:
            return seen[stripe], key
        seen[stripe] = key
    raise AssertionError("pigeonhole guarantees a collision")


def _payload(stream, conversation_id=None):
    payload = {
        "model": "deepseek-chat",
        "stream": stream,
        "messages": [{"role": "user", "content": "hello"}],
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return payload


@pytest.mark.parametrize("stateful", [True, False], ids=["conversation", "stateless"])
def test_unrelated_session_streams_while_another_run_is_in_progress(stateful):
    if stateful:
        first, second = _same_old_stripe(lambda key: f"openai:conversation:{key}")
        requests = [
            dict(payload=_payload(False, first), completion_id="chatcmpl-first"),
            dict(payload=_payload(True, second), completion_id="chatcmpl-second"),
        ]
    else:
        first, second = _same_old_stripe(lambda key: f"openai:request:{key}")
        requests = [
            dict(payload=_payload(False), completion_id=first),
            dict(payload=_payload(True), completion_id=second),
        ]

    first_running = threading.Event()
    release_first = threading.Event()

    def run(query, session_id, send_chunk, **kwargs):
        if not first_running.is_set():
            first_running.set()
            assert release_first.wait(10), "test never released the first run"
        send_chunk({"chunk_type": "content", "delta": session_id})

    def call(request):
        return handle_chat_completions(
            request["payload"],
            authorization="Bearer secret",
            external_api_token="secret",
            run_chat=run,
            completion_id=request["completion_id"],
        )

    long_run = threading.Thread(target=call, args=(requests[0],), daemon=True)
    long_run.start()
    try:
        assert first_running.wait(2)
        # Raised OpenAIAPIError(500, ..., "timeout") on the striped lock.
        frames = "".join(call(requests[1]))
    finally:
        release_first.set()
        long_run.join(timeout=5)

    assert not long_run.is_alive()
    assert "data: [DONE]" in frames
    assert '"finish_reason": "stop"' in frames


def test_session_lock_is_shared_per_session_and_released_when_unused():
    one = openai_compat._session_lock("openai:conversation:a", "agent-1")
    assert openai_compat._session_lock("openai:conversation:a", "agent-1") is one
    assert openai_compat._session_lock("openai:conversation:b", "agent-1") is not one
    assert openai_compat._session_lock("openai:conversation:a", "agent-2") is not one

    with one:
        assert not one.acquire(blocking=False)
    assert one.acquire(blocking=False)
    one.release()

    del one
    gc.collect()
    assert len(openai_compat._SESSION_LOCKS) == 0
