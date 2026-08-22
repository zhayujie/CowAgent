import json
import queue
import threading
from pathlib import Path

import pytest
import web

from channel.web import openai_api, web_channel
from channel.web.openai_api import (
    OpenAIAPIError,
    handle_chat_completions,
)


def _runner(events, calls):
    def run(
        query,
        session_id,
        send_chunk_fn,
        channel_type="",
        agent_id=None,
        request_id=None,
    ):
        calls.append(
            {
                "query": query,
                "session_id": session_id,
                "channel_type": channel_type,
                "agent_id": agent_id,
                "request_id": request_id,
            }
        )
        for event in events:
            send_chunk_fn(event)

    return run


def _http_app(monkeypatch, run_chat, configured_token="secret"):
    monkeypatch.setattr(
        openai_api, "conf", lambda: {"external_api_token": configured_token}
    )
    monkeypatch.setattr(openai_api, "_run_chat_service", run_chat)
    return web.application(
        ("/v1/chat/completions", "OpenAIChatCompletionsHandler"),
        vars(web_channel),
        autoreload=False,
    )


def _post(app, payload, authorization="Bearer secret"):
    return app.request(
        "/v1/chat/completions",
        method="POST",
        data=json.dumps(payload),
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json",
        },
    )


@pytest.mark.parametrize(
    ("configured_token", "authorization", "status_code"),
    [
        ("", "Bearer secret", 503),
        ("secret", "", 401),
        ("secret", "Bearer wrong", 401),
    ],
)
def test_external_api_uses_independent_bearer_auth(
    configured_token, authorization, status_code
):
    with pytest.raises(OpenAIAPIError) as exc_info:
        handle_chat_completions(
            {
                "model": "cowagent",
                "messages": [{"role": "user", "content": "hello"}],
            },
            authorization=authorization,
            external_api_token=configured_token,
            run_chat=lambda *args, **kwargs: None,
        )

    assert exc_info.value.status_code == status_code


@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
def test_bearer_scheme_is_case_insensitive(scheme):
    response = handle_chat_completions(
        {
            "model": "cowagent",
            "messages": [{"role": "user", "content": "hello"}],
        },
        authorization=f"{scheme} secret",
        external_api_token="secret",
        run_chat=_runner([{"chunk_type": "content", "delta": "Hello"}], []),
    )

    assert response["choices"][0]["message"]["content"] == "Hello"


def test_cancel_agent_request_uses_bridge_scoped_key(monkeypatch):
    calls = []

    class FakeAgentBridge:
        agent_registry = type(
            "FakeAgentRegistry", (), {"default_agent_id": "primary"}
        )()

        def _resolve_agent_id(self, agent_id=None):
            calls.append(("resolve", agent_id))
            return agent_id or "primary"

        @staticmethod
        def _cancel_key(agent_id, request_id, default_agent_id):
            calls.append(("scope", agent_id, request_id, default_agent_id))
            return f"{agent_id}::{request_id}"

    class FakeRegistry:
        def cancel_request(self, request_id):
            calls.append(("cancel", request_id))
            return True

    monkeypatch.setattr(
        "bridge.bridge.Bridge",
        lambda: type(
            "FakeBridge",
            (),
            {"get_agent_bridge": lambda self: FakeAgentBridge()},
        )(),
    )
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: FakeRegistry())

    assert openai_api._cancel_agent_request("request-1", agent_id="research") is True
    assert calls == [
        ("resolve", "research"),
        ("scope", "research", "request-1", "primary"),
        ("cancel", "research::request-1"),
    ]


def test_late_cancel_does_not_cancel_new_request_in_same_session(monkeypatch):
    from agent.protocol.cancel import CancelTokenRegistry

    registry = CancelTokenRegistry()
    old_event = registry.register("request-old", session_id="shared-session")
    registry.unregister("request-old")
    new_event = registry.register("request-new", session_id="shared-session")

    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)
    monkeypatch.setattr(
        openai_api,
        "_request_cancel_key",
        lambda request_id, agent_id=None: request_id,
    )

    assert openai_api._cancel_agent_request("request-old") is False
    assert not old_event.is_set()
    assert not new_event.is_set()


def test_non_streaming_completion_maps_content_reasoning_and_tools():
    calls = []
    response = handle_chat_completions(
        {
            "model": "cowagent",
            "conversation_id": "conversation-42",
            "user": "user-7",
            "messages": [
                {"role": "assistant", "content": "previous answer"},
                {"role": "user", "content": "inspect the workspace"},
            ],
        },
        authorization="Bearer secret",
        external_api_token="secret",
        run_chat=_runner(
            [
                {"chunk_type": "reasoning", "delta": "Need a file. "},
                {
                    "chunk_type": "tool_start",
                    "tool": "read",
                    "tool_id": "call-1",
                    "arguments": {"path": "README.md"},
                },
                {
                    "chunk_type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "name": "read",
                            "arguments": {"path": "README.md"},
                            "result": "CowAgent",
                            "status": "success",
                            "elapsed": "0.01s",
                        }
                    ],
                },
                {"chunk_type": "content", "delta": "The workspace is ready."},
            ],
            calls,
        ),
        created=1700000000,
        completion_id="chatcmpl-test",
    )

    assert calls == [
        {
            "query": "inspect the workspace",
            "session_id": "openai:conversation:conversation-42",
            "channel_type": "openai_api",
            "agent_id": None,
            "request_id": "chatcmpl-test",
        }
    ]
    assert response == {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "cowagent",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "The workspace is ready.",
                    "reasoning_content": "Need a file. ",
                    "tool_trace": [
                        {
                            "type": "tool_start",
                            "id": "call-1",
                            "name": "read",
                            "arguments": {"path": "README.md"},
                        },
                        {
                            "type": "tool_result",
                            "id": "call-1",
                            "name": "read",
                            "arguments": {"path": "README.md"},
                            "result": "CowAgent",
                            "status": "success",
                            "elapsed": "0.01s",
                        },
                    ],
                },
                "finish_reason": "stop",
            }
        ],
    }


def test_streaming_completion_uses_standard_deltas_and_additive_cow_events():
    calls = []
    stream = handle_chat_completions(
        {
            "model": "cowagent",
            "stream": True,
            "user": "user-7",
            "messages": [{"role": "user", "content": "hello"}],
        },
        authorization="Bearer secret",
        external_api_token="secret",
        run_chat=_runner(
            [
                {"chunk_type": "reasoning", "delta": "Think."},
                {
                    "chunk_type": "tool_start",
                    "tool": "search",
                    "tool_id": "call-2",
                    "arguments": {"query": "CowAgent"},
                },
                {"chunk_type": "content", "delta": "Hello"},
                {"chunk_type": "content", "delta": " world"},
            ],
            calls,
        ),
        created=1700000000,
        completion_id="chatcmpl-stream",
    )

    frames = list(stream)
    assert frames[-1] == "data: [DONE]\n\n"
    payloads = [
        json.loads(frame.removeprefix("data: ").removesuffix("\n\n"))
        for frame in frames[:-1]
    ]
    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[1]["choices"][0]["delta"] == {"reasoning_content": "Think."}
    assert payloads[1]["cow_event"] == {
        "type": "reasoning",
        "delta": "Think.",
    }
    assert payloads[2]["choices"][0]["delta"] == {}
    assert payloads[2]["cow_event"] == {
        "type": "tool_start",
        "id": "call-2",
        "name": "search",
        "arguments": {"query": "CowAgent"},
    }
    assert [
        payload["choices"][0]["delta"].get("content") for payload in payloads[3:5]
    ] == ["Hello", " world"]
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert calls[0]["session_id"] == "openai:user:user-7"


def test_streaming_agent_failure_before_first_event_returns_500():
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    with pytest.raises(OpenAIAPIError) as exc_info:
        handle_chat_completions(
            {
                "model": "cowagent",
                "stream": True,
                "messages": [{"role": "user", "content": "hello"}],
            },
            authorization="Bearer secret",
            external_api_token="secret",
            run_chat=fail,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "internal_error"
    assert "provider unavailable" not in exc_info.value.message


def test_streaming_agent_failure_after_first_event_finishes_with_error():
    def fail_after_content(
        query,
        session_id,
        send_chunk_fn,
        channel_type="",
        agent_id=None,
        request_id=None,
    ):
        send_chunk_fn({"chunk_type": "content", "delta": "partial"})
        raise RuntimeError("provider unavailable")

    stream = handle_chat_completions(
        {
            "model": "cowagent",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
        authorization="Bearer secret",
        external_api_token="secret",
        run_chat=fail_after_content,
        created=1700000000,
        completion_id="chatcmpl-error",
    )

    frames = list(stream)
    payloads = [
        json.loads(frame.removeprefix("data: ").removesuffix("\n\n"))
        for frame in frames[:-1]
    ]
    assert frames[-1] == "data: [DONE]\n\n"
    assert payloads[1]["choices"][0]["delta"] == {"content": "partial"}
    assert payloads[2]["cow_event"] == {
        "type": "error",
        "message": "CowAgent failed to complete the request.",
    }
    assert payloads[-1]["choices"][0]["finish_reason"] == "error"


def test_streaming_returns_after_first_event_without_waiting_for_completion():
    release_runner = threading.Event()
    prepared_stream = queue.Queue()

    def run(
        query,
        session_id,
        send_chunk_fn,
        channel_type="",
        agent_id=None,
        request_id=None,
    ):
        send_chunk_fn({"chunk_type": "content", "delta": "first"})
        release_runner.wait()
        send_chunk_fn({"chunk_type": "content", "delta": "second"})

    def prepare():
        prepared_stream.put(
            handle_chat_completions(
                {
                    "model": "cowagent",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hello"}],
                },
                authorization="Bearer secret",
                external_api_token="secret",
                run_chat=run,
            )
        )

    caller = threading.Thread(target=prepare)
    caller.start()
    try:
        stream = prepared_stream.get(timeout=1)
    finally:
        release_runner.set()
        caller.join(timeout=1)

    frames = list(stream)
    assert '"content": "first"' in frames[1]
    assert '"content": "second"' in frames[2]


def test_streaming_generator_close_cancels_agent_request_once(monkeypatch):
    release_runner = threading.Event()
    runner_started = threading.Event()
    cancel_calls = []

    def run(
        query,
        session_id,
        send_chunk_fn,
        channel_type="",
        agent_id=None,
        request_id=None,
    ):
        send_chunk_fn({"chunk_type": "content", "delta": "first"})
        runner_started.set()
        release_runner.wait()

    monkeypatch.setattr(
        openai_api,
        "_cancel_agent_request",
        lambda request_id, agent_id=None: cancel_calls.append((request_id, agent_id)),
        raising=False,
    )
    stream = handle_chat_completions(
        {
            "model": "cowagent",
            "stream": True,
            "conversation_id": "close-me",
            "messages": [{"role": "user", "content": "hello"}],
        },
        authorization="Bearer secret",
        external_api_token="secret",
        run_chat=run,
        completion_id="chatcmpl-close",
    )

    try:
        assert runner_started.wait(timeout=1)
        next(stream)
        stream.close()
    finally:
        release_runner.set()

    assert cancel_calls == [("chatcmpl-close", None)]


def test_streaming_timeout_while_waiting_for_session_lock_skips_run_chat(monkeypatch):
    from agent.protocol.cancel import CancelTokenRegistry

    registry = CancelTokenRegistry()
    session_id = "openai:conversation:queued-timeout"
    session_lock = openai_api._SESSION_LOCKS[
        hash(session_id) % len(openai_api._SESSION_LOCKS)
    ]
    run_calls = []
    session_writes = []
    existing_threads = set(threading.enumerate())

    def run(*args, **kwargs):
        run_calls.append((args, kwargs))
        session_writes.append(args[1])

    monkeypatch.setattr(openai_api, "_FIRST_EVENT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)
    monkeypatch.setattr(
        openai_api,
        "_request_cancel_scope",
        lambda request_id, session_id=None, agent_id=None: (
            request_id,
            session_id,
        ),
    )
    monkeypatch.setattr(openai_api, "_cancel_agent_request", lambda *args: False)

    session_lock.acquire()
    try:
        with pytest.raises(OpenAIAPIError) as exc_info:
            handle_chat_completions(
                {
                    "model": "cowagent",
                    "stream": True,
                    "conversation_id": "queued-timeout",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                authorization="Bearer secret",
                external_api_token="secret",
                run_chat=run,
                completion_id="chatcmpl-queued-timeout",
            )
        workers = [
            thread
            for thread in threading.enumerate()
            if thread not in existing_threads
            and thread.name == "openai-chat-completion"
        ]
        assert len(workers) == 1
    finally:
        session_lock.release()

    workers[0].join(timeout=1)
    assert not workers[0].is_alive()
    assert exc_info.value.code == "timeout"
    assert registry.get_event("chatcmpl-queued-timeout") is None
    assert not registry.has_active(session_id)
    assert run_calls == []
    assert session_writes == []


def test_streaming_timeout_after_closed_check_reuses_pre_registered_cancel_event(
    monkeypatch,
):
    from agent.protocol.cancel import CancelTokenRegistry

    registry = CancelTokenRegistry()
    entered_run_chat = threading.Event()
    release_run_chat = threading.Event()
    response_queue = queue.Queue()
    observed_events = []
    agent_runs = []
    history_writes = []
    session_id = "openai:conversation:registration-race"
    completion_id = "chatcmpl-registration-race"
    request_key = f"research::{completion_id}"
    session_key = f"research::{session_id}"
    existing_threads = set(threading.enumerate())

    class FakeAgentBridge:
        agent_registry = type(
            "FakeAgentRegistry", (), {"default_agent_id": "primary"}
        )()

        @staticmethod
        def _resolve_agent_id(agent_id=None):
            return agent_id or "research"

        @staticmethod
        def _cancel_key(agent_id, token, default_agent_id):
            return token if agent_id == default_agent_id else f"{agent_id}::{token}"

    class FakeBridge:
        @staticmethod
        def get_agent_bridge():
            return FakeAgentBridge()

    def run_chat(*args, **kwargs):
        entered_run_chat.set()
        release_run_chat.wait()
        cancel_event = registry.register(request_key, session_id=session_key)
        observed_events.append(cancel_event)
        try:
            if not cancel_event.is_set():
                agent_runs.append(kwargs["request_id"])
                history_writes.append(args[1])
        finally:
            registry.unregister(request_key)

    monkeypatch.setattr("bridge.bridge.Bridge", FakeBridge)
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)
    monkeypatch.setattr(openai_api, "_FIRST_EVENT_TIMEOUT_SECONDS", 0.05)

    def request():
        try:
            handle_chat_completions(
                {
                    "model": "cowagent",
                    "stream": True,
                    "conversation_id": "registration-race",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                authorization="Bearer secret",
                external_api_token="secret",
                run_chat=run_chat,
                completion_id=completion_id,
            )
        except OpenAIAPIError as error:
            response_queue.put(error)

    caller = threading.Thread(target=request)
    caller.start()
    assert entered_run_chat.wait(timeout=1)
    error = response_queue.get(timeout=1)
    pre_registered_event = registry.get_event(request_key)
    session_was_active = registry.has_active(session_key)
    workers = [
        thread
        for thread in threading.enumerate()
        if thread not in existing_threads and thread.name == "openai-chat-completion"
    ]
    assert len(workers) == 1
    release_run_chat.set()
    caller.join(timeout=1)
    workers[0].join(timeout=1)

    assert error.code == "timeout"
    assert observed_events == [pre_registered_event]
    assert pre_registered_event is not None
    assert pre_registered_event.is_set()
    assert session_was_active
    assert agent_runs == []
    assert history_writes == []
    assert registry.get_event(request_key) is None
    assert not registry.has_active(session_key)


def test_streaming_generator_close_while_waiting_for_session_lock_skips_run_chat(
    monkeypatch,
):
    real_queue = queue.Queue
    session_id = "openai:conversation:queued-close"
    session_lock = openai_api._SESSION_LOCKS[
        hash(session_id) % len(openai_api._SESSION_LOCKS)
    ]
    run_calls = []
    session_writes = []
    existing_threads = set(threading.enumerate())

    class PrimedQueue:
        def __init__(self, maxsize):
            self._queue = real_queue(maxsize=maxsize)
            self._first_item = {
                "id": "chatcmpl-queued-close",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "cowagent",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "primed"},
                        "finish_reason": None,
                    }
                ],
            }

        def put(self, item, timeout=None):
            return self._queue.put(item, timeout=timeout)

        def get(self, timeout=None):
            if self._first_item is not None:
                item = self._first_item
                self._first_item = None
                return item
            return self._queue.get(timeout=timeout)

    def run(*args, **kwargs):
        run_calls.append((args, kwargs))
        session_writes.append(args[1])

    monkeypatch.setattr(openai_api.queue, "Queue", PrimedQueue)
    monkeypatch.setattr(openai_api, "_cancel_agent_request", lambda *args: False)

    session_lock.acquire()
    try:
        stream = handle_chat_completions(
            {
                "model": "cowagent",
                "stream": True,
                "conversation_id": "queued-close",
                "messages": [{"role": "user", "content": "hello"}],
            },
            authorization="Bearer secret",
            external_api_token="secret",
            run_chat=run,
            created=1700000000,
            completion_id="chatcmpl-queued-close",
        )
        next(stream)
        stream.close()
        workers = [
            thread
            for thread in threading.enumerate()
            if thread not in existing_threads
            and thread.name == "openai-chat-completion"
        ]
        assert len(workers) == 1
    finally:
        session_lock.release()

    workers[0].join(timeout=1)
    assert not workers[0].is_alive()
    assert run_calls == []
    assert session_writes == []


def test_streaming_normal_completion_does_not_cancel_agent_request(monkeypatch):
    cancel_calls = []
    monkeypatch.setattr(
        openai_api,
        "_cancel_agent_request",
        lambda request_id, agent_id=None: cancel_calls.append((request_id, agent_id)),
        raising=False,
    )
    stream = handle_chat_completions(
        {
            "model": "cowagent",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
        authorization="Bearer secret",
        external_api_token="secret",
        run_chat=_runner([{"chunk_type": "content", "delta": "Hello"}], []),
    )

    assert list(stream)[-1] == "data: [DONE]\n\n"
    assert cancel_calls == []


def test_encoded_stream_close_propagates_to_source():
    close_calls = []

    class Source:
        def __iter__(self):
            return self

        def __next__(self):
            return "data: first\n\n"

        def close(self):
            close_calls.append("closed")

    source = Source()
    stream = openai_api._encode_stream(source)

    assert next(stream) == b"data: first\n\n"
    stream.close()

    assert close_calls == ["closed"]


def test_invalid_messages_return_400():
    with pytest.raises(OpenAIAPIError) as exc_info:
        handle_chat_completions(
            {
                "model": "cowagent",
                "messages": [{"role": "user", "content": [{"type": "text"}]}],
            },
            authorization="Bearer secret",
            external_api_token="secret",
            run_chat=lambda *args, **kwargs: None,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "invalid_request"


def test_non_streaming_agent_failure_returns_500():
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    with pytest.raises(OpenAIAPIError) as exc_info:
        handle_chat_completions(
            {
                "model": "cowagent",
                "messages": [{"role": "user", "content": "hello"}],
            },
            authorization="Bearer secret",
            external_api_token="secret",
            run_chat=fail,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "internal_error"
    assert "provider unavailable" not in exc_info.value.message


@pytest.mark.filterwarnings("ignore:setDaemon\\(\\) is deprecated:DeprecationWarning")
def test_web_channel_binds_openai_chat_route(monkeypatch):
    class RoutesCaptured(Exception):
        pass

    captured = {}

    def capture_application(urls, namespace, autoreload):
        captured["urls"] = urls
        captured["namespace"] = namespace
        captured["autoreload"] = autoreload
        raise RoutesCaptured

    channel = web_channel.WebChannel()
    monkeypatch.setattr(channel, "_cleanup_stale_voice_recordings", lambda: None)
    monkeypatch.setattr(web_channel.web, "application", capture_application)
    monkeypatch.setattr(
        web_channel,
        "conf",
        lambda: {"web_host": "127.0.0.1", "web_port": 9899},
    )

    with pytest.raises(RoutesCaptured):
        channel.startup()

    route_pairs = list(zip(captured["urls"][::2], captured["urls"][1::2]))
    assert (
        "/v1/chat/completions",
        "OpenAIChatCompletionsHandler",
    ) in route_pairs
    assert (
        captured["namespace"]["OpenAIChatCompletionsHandler"]
        is openai_api.OpenAIChatCompletionsHandler
    )
    assert captured["autoreload"] is False


def test_http_post_returns_200_json(monkeypatch):
    app = _http_app(
        monkeypatch,
        _runner([{"chunk_type": "content", "delta": "Hello"}], []),
    )

    response = _post(
        app,
        {
            "model": "cowagent",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status == "200 OK"
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(response.data)["choices"][0]["message"]["content"] == "Hello"


def test_http_post_returns_400_for_invalid_json(monkeypatch):
    app = _http_app(monkeypatch, _runner([], []))

    response = app.request(
        "/v1/chat/completions",
        method="POST",
        data="{",
        headers={
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        },
    )

    assert response.status == "400 Bad Request"
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(response.data) == {
        "error": {
            "message": "Request body must be valid JSON.",
            "type": "invalid_request_error",
            "code": "invalid_json",
        }
    }


def test_http_post_returns_401_for_invalid_bearer_token(monkeypatch):
    app = _http_app(monkeypatch, _runner([], []))

    response = _post(
        app,
        {
            "model": "cowagent",
            "messages": [{"role": "user", "content": "hello"}],
        },
        authorization="Bearer wrong",
    )

    assert response.status == "401 Unauthorized"
    assert json.loads(response.data)["error"]["code"] == "invalid_api_key"


def test_http_post_returns_503_when_external_api_is_disabled(monkeypatch):
    app = _http_app(monkeypatch, _runner([], []), configured_token="")

    response = _post(
        app,
        {
            "model": "cowagent",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status == "503 Service Unavailable"
    assert json.loads(response.data)["error"]["code"] == "api_disabled"


def test_http_stream_returns_500_when_agent_fails_immediately(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    app = _http_app(monkeypatch, fail)
    response = _post(
        app,
        {
            "model": "cowagent",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status == "500 Internal Server Error"
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(response.data)["error"]["code"] == "internal_error"


def test_http_stream_first_event_timeout_returns_500_and_cancels(monkeypatch):
    release_runner = threading.Event()
    runner_started = threading.Event()
    response_queue = queue.Queue()
    cancel_calls = []
    request_ids = []

    def block_before_first_event(*args, **kwargs):
        request_ids.append(kwargs["request_id"])
        runner_started.set()
        release_runner.wait()

    monkeypatch.setattr(openai_api, "_FIRST_EVENT_TIMEOUT_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(
        openai_api,
        "_cancel_agent_request",
        lambda request_id, agent_id=None: cancel_calls.append((request_id, agent_id)),
        raising=False,
    )
    app = _http_app(monkeypatch, block_before_first_event)

    def request():
        response_queue.put(
            _post(
                app,
                {
                    "model": "cowagent",
                    "stream": True,
                    "conversation_id": "timeout",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
        )

    caller = threading.Thread(target=request)
    caller.start()
    try:
        assert runner_started.wait(timeout=1)
        response = response_queue.get(timeout=0.5)
    finally:
        release_runner.set()
        caller.join(timeout=1)

    assert response.status == "500 Internal Server Error"
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(response.data)["error"] == {
        "message": "CowAgent timed out before producing a response.",
        "type": "api_error",
        "code": "timeout",
    }
    assert len(request_ids) == 1
    assert cancel_calls == [(request_ids[0], None)]


def test_http_stream_returns_sse_body_and_done_marker(monkeypatch):
    app = _http_app(
        monkeypatch,
        _runner([{"chunk_type": "content", "delta": "Hello"}], []),
    )

    response = _post(
        app,
        {
            "model": "cowagent",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    body = response.data.decode("utf-8")
    assert response.status == "200 OK"
    assert response.headers["Content-Type"] == "text/event-stream; charset=utf-8"
    assert '"delta": {"role": "assistant"}' in body
    assert '"delta": {"content": "Hello"}' in body
    assert '"finish_reason": "stop"' in body
    assert body.endswith("data: [DONE]\n\n")


def test_route_config_and_english_documentation_expose_the_public_api():
    root = Path(__file__).parents[1]
    config = json.loads((root / "config-template.json").read_text(encoding="utf-8"))
    docs = (root / "docs/channels/web.mdx").read_text(encoding="utf-8")

    assert config["external_api_token"] == ""
    assert "POST /v1/chat/completions" in docs
    assert "Authorization: Bearer" in docs
    assert '"stream": true' in docs
    assert "before the first event" in docs
    assert "30 seconds" in docs
    assert "`cow_event.type=error`" in docs
    assert "`finish_reason=error`" in docs
