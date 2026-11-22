"""OpenAI-compatible HTTP adapter for CowAgent chat completions."""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
import weakref
from typing import Callable, Iterator

from common.log import logger
from common.utils import constant_time_equals
from config import conf


class OpenAIAPIError(Exception):
    """A public API error with an explicit HTTP status."""

    def __init__(self, status_code: int, message: str, code: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code


class _SessionLock:
    """A lock for one (Agent, session), dropped once nobody holds or awaits it."""

    __slots__ = ("_lock", "__weakref__")

    def __init__(self):
        self._lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        return self._lock.acquire(blocking, timeout)

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self._lock.release()


# One lock per (Agent, session). Unrelated sessions never share one, so a long
# run only queues requests in its own conversation. Weak values let an entry
# go away once the last request holding or waiting on it has finished.
_SESSION_LOCKS: "weakref.WeakValueDictionary[tuple, _SessionLock]" = (
    weakref.WeakValueDictionary()
)
_SESSION_LOCKS_GUARD = threading.Lock()
_STREAM_END = object()
_STREAM_ERROR = object()
_FIRST_EVENT_TIMEOUT_SECONDS = 30
# Budget for each later stream event, matching the web SSE stream. Without it
# a stalled run parks the consumer forever and keeps the session lock.
_STREAM_IDLE_TIMEOUT_SECONDS = 600

_TEXT_ROLES = ("system", "developer", "user", "assistant")
_PASSTHROUGH_EVENTS = ("subagent_step", "artifact", "peer_start", "peer_end")


def _authenticate(authorization: str, external_api_token: str) -> None:
    token = str(external_api_token or "")
    if not token:
        raise OpenAIAPIError(
            503,
            "The external chat completions API is disabled.",
            "api_disabled",
        )
    scheme, separator, credential = str(authorization or "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not credential
        or not constant_time_equals(credential.strip(), token)
    ):
        raise OpenAIAPIError(
            401, "Invalid authentication credentials.", "invalid_api_key"
        )


def _served_token() -> str:
    """The API key while the API is on; empty, which refuses every call, while off."""
    cfg = conf()
    if not cfg.get("external_api_enabled"):
        return ""
    return str(cfg.get("external_api_token", "") or "")


def _agent_registry():
    from bridge.bridge import Bridge

    return Bridge().get_agent_bridge().agent_registry


def _resolve_agent(agent_id: str | None) -> str | None:
    """The enabled Agent a request's ``agent_id`` names; None means the default Agent."""
    if agent_id is None:
        return None
    try:
        return _agent_registry().get_addressed(agent_id).id
    except Exception as error:
        raise OpenAIAPIError(
            404,
            f"The agent '{agent_id}' does not exist or is disabled.",
            "agent_not_found",
        ) from error


def _model_catalog() -> list:
    """The providers and models a conversation may switch to."""
    from channel.web.api.sessions import _session_model_catalog

    return _session_model_catalog()


def _resolve_model(model: str | None) -> tuple | None:
    """The ``(provider, model)`` a request names; None keeps the Agent's own model."""
    if model is None:
        return None
    for provider in _model_catalog():
        if model in provider.get("models") or ():
            return provider["id"], model
    raise OpenAIAPIError(
        404,
        f"The model '{model}' is not available. Use GET /v1/models to list the available models.",
        "model_not_found",
    )


def _agent_model_name(agent_id: str | None) -> str:
    """The model an Agent answers on when a request names none."""
    try:
        pinned = _agent_registry().get(agent_id).model
    except Exception:
        pinned = None
    return pinned or conf().get("model") or ""


def _message_text(message: dict) -> str:
    """The text of one message; content may be a string or a list of text parts."""
    content = message.get("content")
    if content is None and message.get("role") == "assistant":
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if (
                not isinstance(part, dict)
                or part.get("type") != "text"
                or not isinstance(part.get("text"), str)
            ):
                raise OpenAIAPIError(
                    400, "Only text content parts are supported.", "invalid_request"
                )
            texts.append(part["text"])
        return "".join(texts)
    raise OpenAIAPIError(
        400, "Message content must be a string or an array of text parts.", "invalid_request"
    )


def _request_values(payload: dict, completion_id: str) -> dict:
    if not isinstance(payload, dict):
        raise OpenAIAPIError(
            400, "Request body must be a JSON object.", "invalid_request"
        )

    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise OpenAIAPIError(400, "'model' must be a string.", "invalid_request")
    model = (model or "").strip()

    agent_id = payload.get("agent_id")
    if agent_id is not None and (not isinstance(agent_id, str) or not agent_id.strip()):
        raise OpenAIAPIError(
            400, "'agent_id' must be a non-empty string.", "invalid_request"
        )

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise OpenAIAPIError(
            400, "'messages' must be a non-empty array.", "invalid_request"
        )

    turns = []
    for message in messages:
        if not isinstance(message, dict):
            raise OpenAIAPIError(
                400, "Each message must be an object.", "invalid_request"
            )
        role = message.get("role")
        if role not in _TEXT_ROLES:
            raise OpenAIAPIError(
                400, "Only text chat messages are supported.", "invalid_request"
            )
        text = _message_text(message)
        if role in ("user", "assistant") and text.strip():
            turns.append((role, text))

    last_user = max(
        (index for index, (role, _) in enumerate(turns) if role == "user"),
        default=None,
    )
    if last_user is None:
        raise OpenAIAPIError(
            400,
            "'messages' must contain a non-empty user message.",
            "invalid_request",
        )
    query = turns[last_user][1]

    conversation_id = payload.get("conversation_id")
    if conversation_id is not None and (
        not isinstance(conversation_id, str) or not conversation_id.strip()
    ):
        raise OpenAIAPIError(
            400, "'conversation_id' must be a non-empty string.", "invalid_request"
        )

    # A named conversation keeps its history on the server. Otherwise the
    # request is self-contained: the earlier messages are the context, and
    # nothing is kept once it is answered.
    transcript = None
    if conversation_id:
        session_id = f"openai:conversation:{conversation_id.strip()}"
    else:
        session_id = f"openai:request:{completion_id}"
        transcript = [
            {"role": role, "content": [{"type": "text", "text": text}]}
            for role, text in turns[:last_user]
        ]

    stream = payload.get("stream", False)
    if not isinstance(stream, bool):
        raise OpenAIAPIError(400, "'stream' must be a boolean.", "invalid_request")
    stream_options = payload.get("stream_options")
    if stream_options is not None and not isinstance(stream_options, dict):
        raise OpenAIAPIError(
            400, "'stream_options' must be an object.", "invalid_request"
        )
    include_usage = bool(stream_options and stream_options.get("include_usage") is True)

    return {
        "model": model or None,
        "agent_id": agent_id.strip() if agent_id else None,
        "query": query,
        "session_id": session_id,
        "transcript": transcript,
        "stream": stream,
        "include_usage": include_usage,
    }


def _openai_usage(run_usage) -> dict | None:
    """A run's provider usage, summed over its model calls, in OpenAI's shape."""
    if not isinstance(run_usage, dict) or not run_usage:
        return None

    def count(key: str) -> int:
        try:
            return max(0, int(run_usage.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    prompt = count("prompt_tokens")
    completion = count("completion_tokens")
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": count("total_tokens") or prompt + completion,
        "prompt_tokens_details": {"cached_tokens": count("prompt_cache_hit_tokens")},
    }


def _base_chunk(
    completion_id: str,
    created: int,
    model: str,
    delta: dict,
    finish_reason=None,
    cow_event: dict | None = None,
) -> dict:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if cow_event is not None:
        payload["cow_event"] = cow_event
    return payload


class _ToolEvents:
    """Turns the Agent's tool and teammate chunks into ``cow_event`` objects.

    A call is reported when it starts and again when it finishes, with its
    arguments; the closing batch of a turn repeats results already reported.
    """

    def __init__(self):
        self._arguments = {}
        self._finished = set()

    def __call__(self, chunk: dict) -> list[dict]:
        chunk_type = chunk.get("chunk_type")
        if chunk_type == "tool_start":
            arguments = chunk.get("arguments") or {}
            self._arguments[chunk.get("tool_id")] = arguments
            return [
                {
                    "type": "tool_start",
                    "id": chunk.get("tool_id"),
                    "name": chunk.get("tool"),
                    "arguments": arguments,
                }
            ]
        if chunk_type == "tool_end":
            call_id = chunk.get("tool_id")
            self._finished.add(call_id)
            return [
                {
                    "type": "tool_result",
                    "id": call_id,
                    "name": chunk.get("tool"),
                    "arguments": self._arguments.pop(call_id, {}),
                    "result": chunk.get("result", ""),
                    "status": chunk.get("status"),
                    "elapsed": chunk.get("elapsed"),
                }
            ]
        if chunk_type == "tool_calls":
            events = []
            for item in chunk.get("tool_calls") or []:
                if item.get("id") in self._finished:
                    continue
                events.append(
                    {
                        "type": "tool_result",
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "arguments": item.get("arguments") or {},
                        "result": item.get("result", ""),
                        "status": item.get("status"),
                        "elapsed": item.get("elapsed"),
                    }
                )
            return events
        if chunk_type in _PASSTHROUGH_EVENTS:
            event = dict(chunk)
            event["type"] = event.pop("chunk_type")
            return [event]
        return []


def _sse_frame(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _session_lock(session_id: str, agent_id: str | None = None) -> _SessionLock:
    owner = agent_id or _agent_registry().default_agent_id
    key = (owner, session_id)
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(key)
        if lock is None:
            lock = _SessionLock()
            _SESSION_LOCKS[key] = lock
        return lock


def _request_cancel_scope(
    request_id: str,
    session_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[str, str | None]:
    """Return the request key and session group used by ChatService."""
    from bridge.bridge import Bridge

    agent_bridge = Bridge().get_agent_bridge()
    resolved_agent_id = agent_bridge._resolve_agent_id(agent_id)
    default_agent_id = agent_bridge.agent_registry.default_agent_id
    request_key = agent_bridge._cancel_key(
        resolved_agent_id, request_id, default_agent_id
    )
    session_key = (
        agent_bridge._cancel_key(resolved_agent_id, session_id, default_agent_id)
        if session_id
        else None
    )
    return request_key, session_key


def _request_cancel_key(request_id: str, agent_id: str | None = None) -> str:
    """Return the Agent-scoped cancellation key for one request."""
    return _request_cancel_scope(request_id, agent_id=agent_id)[0]


def _cancel_agent_request(request_id: str, agent_id: str | None = None) -> bool:
    """Cancel one request without affecting newer runs in the same session."""
    from agent.protocol import get_cancel_registry

    return get_cancel_registry().cancel_request(
        _request_cancel_key(request_id, agent_id)
    )


def _run_kwargs(values: dict, agent_id: str | None, completion_id: str) -> dict:
    kwargs = {
        "channel_type": "openai_api",
        "agent_id": agent_id,
        "request_id": completion_id,
    }
    if values.get("model_route"):
        kwargs["model_override"] = values["model_route"]
    if values["transcript"] is not None:
        kwargs["transcript"] = values["transcript"]
        kwargs["ephemeral"] = True
    return kwargs


def _stream_completion(
    run_chat: Callable,
    values: dict,
    agent_id: str | None,
    completion_id: str,
    created: int,
) -> Iterator[str]:
    from agent.protocol import get_cancel_registry

    query = values["query"]
    session_id = values["session_id"]
    model = values["model"]
    registry = get_cancel_registry()
    cancel_key, scoped_session_key = _request_cancel_scope(
        completion_id, session_id, agent_id
    )
    registry.register(cancel_key, session_id=scoped_session_key)

    output = queue.Queue(maxsize=256)
    closed = threading.Event()
    tool_events = _ToolEvents()
    run_usage = {}

    def publish(item) -> None:
        while not closed.is_set():
            try:
                output.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def send_chunk(chunk: dict) -> None:
        chunk_type = chunk.get("chunk_type")
        if chunk_type == "content" and chunk.get("delta"):
            publish(
                _base_chunk(completion_id, created, model, {"content": chunk["delta"]})
            )
        elif chunk_type == "reasoning" and chunk.get("delta"):
            publish(
                _base_chunk(
                    completion_id,
                    created,
                    model,
                    {"reasoning_content": chunk["delta"]},
                    cow_event={"type": "reasoning", "delta": chunk["delta"]},
                )
            )
        else:
            for event in tool_events(chunk):
                publish(_base_chunk(completion_id, created, model, {}, cow_event=event))

    def execute() -> None:
        try:
            with _session_lock(session_id, agent_id):
                if closed.is_set():
                    return
                usage = run_chat(
                    query,
                    session_id,
                    send_chunk,
                    **_run_kwargs(values, agent_id, completion_id),
                )
                if isinstance(usage, dict):
                    run_usage.update(usage)
        except Exception:  # noqa: BLE001 - worker boundary becomes an SSE error
            logger.exception("[OpenAI API] Chat completion failed")
            publish(_STREAM_ERROR)
        finally:
            try:
                publish(_STREAM_END)
            finally:
                registry.unregister(cancel_key)

    worker = threading.Thread(
        target=execute, name="openai-chat-completion", daemon=True
    )
    try:
        worker.start()
    except Exception:
        registry.unregister(cancel_key)
        raise
    try:
        first_item = output.get(timeout=_FIRST_EVENT_TIMEOUT_SECONDS)
    except queue.Empty as error:
        closed.set()
        _cancel_agent_request(completion_id, agent_id)
        raise OpenAIAPIError(
            500, "CowAgent timed out before producing a response.", "timeout"
        ) from error
    if first_item is _STREAM_ERROR:
        closed.set()
        raise OpenAIAPIError(
            500, "CowAgent failed to complete the request.", "internal_error"
        )

    def frames() -> Iterator[str]:
        finish_reason = "stop"
        completed = False
        item = first_item
        try:
            yield _sse_frame(
                _base_chunk(completion_id, created, model, {"role": "assistant"})
            )
            timed_out = False
            while item is not _STREAM_END:
                if item is _STREAM_ERROR:
                    finish_reason = "error"
                    yield _sse_frame(
                        _base_chunk(
                            completion_id,
                            created,
                            model,
                            {},
                            cow_event={
                                "type": "error",
                                "message": "CowAgent failed to complete the request.",
                            },
                        )
                    )
                else:
                    yield _sse_frame(item)
                try:
                    item = output.get(timeout=_STREAM_IDLE_TIMEOUT_SECONDS)
                except queue.Empty:
                    # The worker stalled. completed stays False so the finally below cancels
                    # the run and releases the session lock.
                    timed_out = True
                    finish_reason = "error"
                    yield _sse_frame(
                        _base_chunk(
                            completion_id,
                            created,
                            model,
                            {},
                            cow_event={
                                "type": "error",
                                "message": (
                                    "CowAgent stopped producing events before the "
                                    "stream finished."
                                ),
                            },
                        )
                    )
                    break
            completed = not timed_out
            yield _sse_frame(
                _base_chunk(
                    completion_id,
                    created,
                    model,
                    {},
                    finish_reason=finish_reason,
                )
            )
            usage = _openai_usage(run_usage)
            if values["include_usage"] and usage is not None:
                yield _sse_frame(
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [],
                        "usage": usage,
                    }
                )
            yield "data: [DONE]\n\n"
        finally:
            closed.set()
            if not completed:
                _cancel_agent_request(completion_id, agent_id)

    return frames()


def _non_stream_completion(
    run_chat: Callable,
    values: dict,
    agent_id: str | None,
    completion_id: str,
    created: int,
) -> dict:
    session_id = values["session_id"]
    content = []
    reasoning = []
    tool_trace = []
    tool_events = _ToolEvents()

    def send_chunk(chunk: dict) -> None:
        chunk_type = chunk.get("chunk_type")
        if chunk_type == "content":
            content.append(chunk.get("delta") or "")
        elif chunk_type == "reasoning":
            reasoning.append(chunk.get("delta") or "")
        else:
            # A finished call carries its arguments, so the start adds nothing here.
            tool_trace.extend(
                event for event in tool_events(chunk) if event["type"] != "tool_start"
            )

    # Registered like the streaming path so a session cancel can reach it.
    from agent.protocol import get_cancel_registry

    registry = get_cancel_registry()
    cancel_key, scoped_session_key = _request_cancel_scope(
        completion_id, session_id, agent_id
    )
    registry.register(cancel_key, session_id=scoped_session_key)

    try:
        with _session_lock(session_id, agent_id):
            run_usage = run_chat(
                values["query"],
                session_id,
                send_chunk,
                **_run_kwargs(values, agent_id, completion_id),
            )
    except Exception as error:
        logger.exception("[OpenAI API] Chat completion failed")
        raise OpenAIAPIError(
            500, "CowAgent failed to complete the request.", "internal_error"
        ) from error
    finally:
        registry.unregister(cancel_key)

    message = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if tool_trace:
        message["tool_trace"] = tool_trace
    response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": values["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "stop",
            }
        ],
    }
    usage = _openai_usage(run_usage)
    if usage is not None:
        response["usage"] = usage
    return response


def _encode_stream(stream: Iterator[str]) -> Iterator[bytes]:
    """Encode SSE frames while propagating client disconnects to the source."""
    try:
        for frame in stream:
            yield frame.encode("utf-8")
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()


def handle_chat_completions(
    payload: dict,
    authorization: str,
    external_api_token: str,
    run_chat: Callable,
    created: int | None = None,
    completion_id: str | None = None,
):
    """Validate one request and return a completion dict or SSE iterator."""
    _authenticate(authorization, external_api_token)
    completion_id = completion_id or f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time()) if created is None else int(created)
    values = _request_values(payload, completion_id)
    agent_id = _resolve_agent(values["agent_id"])
    values["model_route"] = _resolve_model(values["model"])
    values["model"] = values["model"] or _agent_model_name(agent_id)
    if values["stream"]:
        return _stream_completion(run_chat, values, agent_id, completion_id, created)
    return _non_stream_completion(run_chat, values, agent_id, completion_id, created)


def handle_list_models(authorization: str, external_api_token: str) -> dict:
    """Every configured chat model a request may name."""
    _authenticate(authorization, external_api_token)
    data = []
    seen = set()
    for provider in _model_catalog():
        for name in provider.get("models") or ():
            if name in seen:
                continue
            seen.add(name)
            data.append({"id": name, "object": "model", "created": 0, "owned_by": provider["id"]})
    return {"object": "list", "data": data}


def _run_chat_service(*args, ephemeral: bool = False, **kwargs):
    """Run one turn; an ephemeral one is neither stored nor kept in memory."""
    from agent.chat.service import ChatService
    from bridge.bridge import Bridge

    agent_bridge = Bridge().get_agent_bridge()
    try:
        return ChatService(agent_bridge).run(*args, persist=not ephemeral, **kwargs)
    finally:
        if ephemeral:
            agent_bridge.clear_session(args[1], kwargs.get("agent_id"))


def _error_body(error: OpenAIAPIError) -> str:
    return json.dumps(
        {
            "error": {
                "message": error.message,
                "type": (
                    "invalid_request_error"
                    if error.status_code in (400, 404)
                    else "api_error"
                ),
                "code": error.code,
            }
        },
        ensure_ascii=False,
    )


_STATUS_LINES = {
    400: "400 Bad Request",
    401: "401 Unauthorized",
    404: "404 Not Found",
    500: "500 Internal Server Error",
    503: "503 Service Unavailable",
}

# Bearer-authenticated and cookie-free, so callers on any origin may use it.
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


def _cors() -> None:
    import web

    for name, value in _CORS_HEADERS.items():
        web.header(name, value)


def _raise_http_error(error: OpenAIAPIError):
    import web

    raise web.HTTPError(
        _STATUS_LINES[error.status_code],
        {"Content-Type": "application/json; charset=utf-8", **_CORS_HEADERS},
        _error_body(error),
    )


class _OpenAIHandler:
    def OPTIONS(self):
        import web

        _cors()
        web.ctx.status = "204 No Content"
        return ""


class OpenAIChatCompletionsHandler(_OpenAIHandler):
    """web.py handler for ``POST /v1/chat/completions``."""

    def POST(self):
        import web

        try:
            raw_body = web.data()
            try:
                payload = json.loads(raw_body) if raw_body else {}
            except (TypeError, ValueError) as error:
                raise OpenAIAPIError(
                    400, "Request body must be valid JSON.", "invalid_json"
                ) from error

            result = handle_chat_completions(
                payload,
                authorization=web.ctx.env.get("HTTP_AUTHORIZATION", ""),
                external_api_token=_served_token(),
                run_chat=_run_chat_service,
            )
        except OpenAIAPIError as error:
            _raise_http_error(error)

        _cors()
        if isinstance(result, dict):
            web.header("Content-Type", "application/json; charset=utf-8")
            return json.dumps(result, ensure_ascii=False)

        web.header("Content-Type", "text/event-stream; charset=utf-8")
        web.header("Cache-Control", "no-cache")
        web.header("X-Accel-Buffering", "no")
        return _encode_stream(result)


class OpenAIModelsHandler(_OpenAIHandler):
    """web.py handler for ``GET /v1/models``."""

    def GET(self):
        import web

        try:
            result = handle_list_models(
                authorization=web.ctx.env.get("HTTP_AUTHORIZATION", ""),
                external_api_token=_served_token(),
            )
        except OpenAIAPIError as error:
            _raise_http_error(error)
        _cors()
        web.header("Content-Type", "application/json; charset=utf-8")
        return json.dumps(result, ensure_ascii=False)
