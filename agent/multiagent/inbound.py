"""Serve an incoming hand-off: a delegated sub-task, a turn the user addressed
to a local teammate (``mode=speak``, answered as itself), or clearing that
teammate's context (``mode=clear``)."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Callable

from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from common.log import logger

CHUNK_EVENT = "event"
CHUNK_RESULT = "result"


def serve_invoke(payload: dict, agent_bridge, send_chunk: Callable[[dict], None]) -> None:
    """Run one incoming hand-off, reporting through ``send_chunk``; never raises.

    payload: request_id, mode ("delegate" | "speak" | "clear"), source_agent_id,
    source_name, target_agent_id, target_aliases, task, root_session_id,
    trace, depth, members, peers, history (speak only), timeout.
    """
    from agent.multiagent import MODE_CLEAR, MODE_SPEAK, get_transport
    from agent.tools.agent_delegate.agent_delegate import (
        TASK_SOURCE,
        AgentDelegateTool,
        DelegationPolicy,
        _DelegateView,
        _relay_lock,
        delegated_prompt,
        delegated_result_text,
    )

    request_id = str(payload.get("request_id") or "")
    source_id = str(payload.get("source_agent_id") or "").strip() or "unknown"
    source_name = str(payload.get("source_name") or source_id).strip() or source_id
    task = str(payload.get("task") or "").strip()
    addressed_id = str(payload.get("target_agent_id") or "").strip()

    def fail(error: str, agent_id: str = addressed_id, agent_name: str = "") -> None:
        logger.warning(f"[MultiAgent] hand-off {request_id or '?'} refused: {error}")
        send_chunk({
            "chunk_type": CHUNK_RESULT,
            "request_id": request_id,
            "status": "failed",
            "error": error,
            "agent_id": agent_id,
            "agent_name": agent_name,
        })

    mode = str(payload.get("mode") or "").strip()

    if agent_bridge is None:
        return fail("agent runtime not available")
    if not addressed_id or (not task and mode != MODE_CLEAR):
        return fail("target_agent_id and task are required")

    try:
        target = agent_bridge.agent_registry.get_addressed(addressed_id, require_enabled=True)
    except Exception:
        return fail(f"Target Agent '{addressed_id}' is not available")

    if mode == MODE_CLEAR:
        # Not a turn: no policy, no roster, nothing to stream.
        return _serve_clear(
            payload, send_chunk, target=target, request_id=request_id
        )

    try:
        from config import conf

        policy = DelegationPolicy.from_config(conf().get("agent_delegation", {}))
    except (TypeError, ValueError) as exc:
        return fail(f"Invalid delegation policy: {exc}", target.id, target.name)
    if not policy.enabled:
        return fail("Agent delegation is disabled", target.id, target.name)
    if len(task) > policy.max_message_chars:
        return fail(
            f"Delegated task exceeds {policy.max_message_chars} characters", target.id, target.name
        )

    # The caller may know this Agent by another id; fold every such alias onto
    # the local id so the chain and roster compare against what runs here.
    aliases = {addressed_id, *(str(a).strip() for a in payload.get("target_aliases") or [] if a)}
    aliases.discard("")

    def local(agent_id) -> str:
        agent_id = str(agent_id or "").strip()
        return target.id if agent_id in aliases else agent_id

    trace = tuple(local(t) for t in (payload.get("trace") or []) if str(t or "").strip())
    if not trace or trace[-1] != target.id:
        trace = (*trace, target.id)
    if target.id in trace[:-1]:
        return fail(f"Delegation cycle rejected: {' -> '.join(trace)}", target.id, target.name)

    try:
        depth = int(payload.get("depth") or (len(trace) - 1))
    except (TypeError, ValueError):
        depth = len(trace) - 1
    if depth > policy.max_depth:
        return fail(
            f"Delegation depth {depth} exceeds the maximum {policy.max_depth}", target.id, target.name
        )

    members = []
    for member_id in payload.get("members") or []:
        member_id = local(member_id)
        if member_id and member_id != target.id and member_id not in members:
            members.append(member_id)
    # Let this process name the rest of the team, wherever they live, so the
    # teammate can hand work onward. Its own aliases are not peers.
    transport = get_transport()
    if transport is not None:
        transport.register_peers(
            p for p in (payload.get("peers") or [])
            if isinstance(p, dict) and str(p.get("id") or "").strip() not in aliases
        )

    root_session_id = str(payload.get("root_session_id") or uuid.uuid4())

    if mode == MODE_SPEAK:
        return _serve_speak(
            payload, agent_bridge, send_chunk, target=target, local=local,
            members=members, request_id=request_id, task=task,
            root_session_id=root_session_id,
        )

    try:
        timeout = float(payload.get("timeout") or policy.timeout_seconds)
    except (TypeError, ValueError):
        timeout = policy.timeout_seconds

    session_id = AgentDelegateTool._session_id(source_id, target.id, root_session_id)
    from common.utils import current_agent_run_id

    run_id = uuid.uuid4().hex

    context = Context(ContextType.TEXT, task, kwargs={})
    context["session_id"] = session_id
    context["request_id"] = request_id or f"delegate_{uuid.uuid4().hex}"
    context["receiver"] = target.id
    context["isgroup"] = False
    context["channel_type"] = "agent"
    context["agent_id"] = target.id
    context["is_delegated_task"] = True
    context["delegated_by"] = source_id
    context["delegation_depth"] = depth
    context["delegation_trace"] = list(trace)
    context["delegation_root_session"] = root_session_id
    context["delegation_members"] = members
    context["run_id"] = run_id
    context["parent_run_id"] = current_agent_run_id() or ""
    context["task_source"] = TASK_SOURCE

    # The caller's side brackets and attributes these; here we only decide what
    # crosses the wire, and it is the same set a local hand-off relays.
    _forwarded = (*_DelegateView.RELAYED, _DelegateView.START, _DelegateView.END)

    def forward(event) -> None:
        if isinstance(event, dict) and event.get("type") in _forwarded:
            try:
                send_chunk({"chunk_type": CHUNK_EVENT, "request_id": request_id, "event": event})
            except Exception as exc:
                logger.debug(f"[MultiAgent] step forward failed: {exc}")

    lock = _relay_lock(session_id)
    if not lock.acquire(timeout=timeout):
        return fail("timed out waiting for the teammate to be free", target.id, target.name)
    started_at = time.monotonic()
    logger.info(
        f"[MultiAgent] serving hand-off {request_id or '?'}: {source_id} -> {target.id}, depth={depth}"
    )
    try:
        reply = agent_bridge.agent_reply(
            delegated_prompt(source_name, source_id, task), context=context, on_event=forward
        )
    except Exception as exc:
        return fail(str(exc), target.id, target.name)
    finally:
        lock.release()
    duration = time.monotonic() - started_at

    if reply is not None and reply.type == ReplyType.ERROR:
        return fail(str(reply.content), target.id, target.name)
    send_chunk({
        "chunk_type": CHUNK_RESULT,
        "request_id": request_id,
        "status": "done",
        "content": delegated_result_text(reply),
        "agent_id": target.id,
        "agent_name": target.name,
        "duration": round(duration, 3),
    })


def _serve_speak(
    payload: dict,
    agent_bridge,
    send_chunk: Callable[[dict], None],
    *,
    target,
    local: Callable[[str], str],
    members: list,
    request_id: str,
    task: str,
    root_session_id: str,
) -> None:
    """Answer as ``target`` on its own copy of the conversation, seeded with the
    handed-over transcript; every chunk is forwarded as an event."""
    from agent.chat.service import ChatService

    def fail(error: str) -> None:
        logger.warning(f"[MultiAgent] speaking turn {request_id or '?'} failed: {error}")
        send_chunk({
            "chunk_type": CHUNK_RESULT,
            "request_id": request_id,
            "status": "failed",
            "error": error,
            "agent_id": target.id,
            "agent_name": target.name,
        })

    session_id = _speak_session_id(root_session_id)
    transcript = _attributed_history(payload.get("history"), local, target.id)
    spoken = []

    def relay(chunk) -> None:
        if not isinstance(chunk, dict):
            return
        if chunk.get("chunk_type") == "content":
            spoken.append(str(chunk.get("delta") or ""))
        try:
            send_chunk({
                "chunk_type": CHUNK_EVENT,
                "request_id": request_id,
                "event": {"type": "chunk", "data": chunk},
            })
        except Exception as exc:
            logger.debug(f"[MultiAgent] chunk forward failed: {exc}")

    started_at = time.monotonic()
    logger.info(
        f"[MultiAgent] speaking turn {request_id or '?'}: {target.id} answers in "
        f"conversation {root_session_id} ({len(transcript)} messages of history)"
    )
    try:
        ChatService(agent_bridge).run(
            query=task,
            session_id=session_id,
            send_chunk_fn=relay,
            channel_type="agent",
            agent_id=target.id,
            request_id=request_id or None,
            members=members,
            transcript=transcript,
        )
    except Exception as exc:
        return fail(str(exc))

    send_chunk({
        "chunk_type": CHUNK_RESULT,
        "request_id": request_id,
        "status": "done",
        "content": "".join(spoken),
        "agent_id": target.id,
        "agent_name": target.name,
        "duration": round(time.monotonic() - started_at, 3),
    })


def _serve_clear(payload: dict, send_chunk: Callable[[dict], None], *, target, request_id: str) -> None:
    """Clear this Agent's context for a conversation kept elsewhere."""
    from agent.chat.session_service import SessionService

    root_session_id = str(payload.get("root_session_id") or "")
    result = {
        "chunk_type": CHUNK_RESULT,
        "request_id": request_id,
        "status": "done",
        "agent_id": target.id,
        "agent_name": target.name,
    }
    if not root_session_id:
        send_chunk({**result, "status": "failed", "error": "root_session_id is required"})
        return
    try:
        SessionService().clear_context(
            _speak_session_id(root_session_id), agent_id=target.id, fanout=False
        )
        logger.info(f"[MultiAgent] cleared {target.id}'s context for conversation {root_session_id}")
    except Exception as exc:
        send_chunk({**result, "status": "failed", "error": str(exc)})
        return
    send_chunk(result)


def _speak_session_id(root_session_id: str) -> str:
    """Local session for a conversation kept elsewhere; stable across turns."""
    digest = hashlib.sha256(root_session_id.encode("utf-8")).hexdigest()[:16]
    return f"team_{digest}"


def _attributed_history(raw, local: Callable[[str], str], reader_id: str) -> list:
    """Wire history -> attributed messages, same as the shared-transcript restore."""
    from bridge.agent_initializer import AgentInitializer

    messages = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        text = str(entry.get("text") or "")
        if role not in ("user", "assistant") or not text:
            continue
        message = {"role": role, "content": [{"type": "text", "text": text}]}
        author = local(entry.get("agent_id")) if role == "assistant" else ""
        if author:
            message["agent_id"] = author
        messages.append(message)
    return AgentInitializer._attribute_history(messages, reader_id)
