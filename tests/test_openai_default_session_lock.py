"""Equivalent default-Agent routes serialize one persistent conversation."""

import json
import threading
from types import SimpleNamespace

import pytest
import web

from agent.registry import AgentProfile, AgentRegistry
from channel.web.api import openai_compat as api


@pytest.fixture
def console(tmp_path, monkeypatch):
    # Each (Agent, session) has its own lock, so no ids need to be picked to
    # dodge a shared lock stripe.
    primary, other = "primary", "other"
    registry = AgentRegistry([
        AgentProfile(primary, "Primary", str(tmp_path / "primary")),
        AgentProfile(other, "Other", str(tmp_path / "other")),
    ], default_agent_id=primary)
    monkeypatch.setattr(api, "_agent_registry", lambda: registry)
    monkeypatch.setattr(api, "_request_cancel_scope", lambda request, session_id=None, agent_id=None:
                        (request, f"{agent_id or primary}:{session_id}"))
    monkeypatch.setattr(api, "conf", lambda: {
        "external_api_enabled": True, "external_api_token": "fixture-token", "model": "fixture-model",
    })
    state = SimpleNamespace(active=0, maximum=0, first_started=threading.Event(),
                            second_started=threading.Event(), release_first=threading.Event())
    guard = threading.Lock()

    def run(query, session_id, send_chunk, **kwargs):
        with guard:
            state.active += 1
            state.maximum = max(state.maximum, state.active)
        try:
            if query == "first":
                state.first_started.set()
                assert state.release_first.wait(5), "test coordinator did not release its first request"
            else:
                state.second_started.set()
            send_chunk({"chunk_type": "content", "delta": query})
        finally:
            with guard:
                state.active -= 1

    monkeypatch.setattr(api, "_run_chat_service", run)
    app = web.application(("/v1/chat/completions", "OpenAIChatCompletionsHandler"), vars(api), autoreload=False)
    return app, primary, other, state


def _overlapping_requests(console, first_stream, second_agent):
    app, primary, other, state = console
    responses, errors = [], []

    def request(query, stream, agent_id):
        body = {"conversation_id": "shared", "messages": [{"role": "user", "content": query}], "stream": stream}
        if agent_id is not None:
            body["agent_id"] = agent_id
        try:
            response = app.request("/v1/chat/completions", method="POST", data=json.dumps(body),
                                   headers={"Authorization": "Bearer fixture-token"})
            responses.append(response)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=request, args=("first", first_stream, None), daemon=True),
               threading.Thread(target=request, args=("second", False, second_agent), daemon=True)]
    try:
        threads[0].start()
        assert state.first_started.wait(2)
        threads[1].start()
        concurrent = state.second_started.wait(1)
    finally:
        state.release_first.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=3)
    assert not any(t.is_alive() for t in threads)
    assert not errors, errors
    assert len(responses) == 2
    assert all(response.status == "200 OK" for response in responses)
    return concurrent, state.maximum


@pytest.mark.parametrize("first_stream", [False, True])
def test_omitted_and_explicit_default_agent_cannot_overlap_one_conversation(console, first_stream):
    _, primary, _, _ = console
    concurrent, maximum = _overlapping_requests(console, first_stream, primary)
    assert not concurrent, "two default-Agent routes entered the same conversation at once"
    assert maximum == 1


def test_different_agents_keep_independent_conversation_execution(console):
    _, _, other, _ = console
    concurrent, maximum = _overlapping_requests(console, False, other)
    assert concurrent
    assert maximum == 2
