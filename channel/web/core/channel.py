"""The web console's channel: everything that is not a request handler.

WebChannel is the ChatChannel side of the console -- receiving a message,
running it through the bridge, streaming the reply back over SSE -- plus the
lifecycle of the HTTP server it all rides on. The request handlers live in
channel/web/web_channel.py, and the two only meet through channel/web/_common.py
and the URL table, so neither imports the other at module scope.
"""

import datetime
import json
import logging
import os
import random
import re
import shutil
import threading
import time
import uuid
from queue import Queue, Empty
from typing import List, Optional
from urllib.parse import quote

import web

from bridge.context import *
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.web.core import providers
from channel.web.core._common import (
    _addressed_agent_id, _build_artifact_payload, _cancel_reply_text,
    _desktop_token_matches, _ensure_list, _get_upload_dir, _get_workspace_root,
    IMAGE_EXTENSIONS, _is_loopback_request, _is_password_enabled,
    _is_within_directory, _log_bind_failure, MAX_LOCAL_IMPORT_BYTES,
    _raw_web_input, _read_uploaded_file_bytes,
    _resolve_upload_path, _rewrite_relative_media, _sanitize_upload_id,
    _scoped_agent_id, SERVING, _session_roster, SSEStreamState,
    _steer_reply_text, VIDEO_EXTENSIONS, WebMessage,
)
from common import i18n
from common.log import logger
from common.singleton import singleton
from config import conf


@singleton
class WebChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE]
    _instance = None
    SSE_REPLAY_MAX_EVENTS = 5000
    SSE_REPLAY_MAX_BYTES = 4 * 1024 * 1024
    SSE_POST_DONE_TAIL_SECONDS = 60
    SSE_COMPLETED_TTL_SECONDS = 60
    SSE_IDLE_TIMEOUT_SECONDS = 1800

    # def __new__(cls):
    #     if cls._instance is None:
    #         cls._instance = super(WebChannel, cls).__new__(cls)
    #     return cls._instance

    def __init__(self):
        super().__init__()
        self.msg_id_counter = 0
        self.session_queues = {}  # session_id -> Queue (fallback polling)
        self.request_to_session = {}  # request_id -> session_id
        self.request_to_agent = {}  # request_id -> agent_id
        self.sse_streams = {}  # request_id -> SSEStreamState
        self._sse_streams_lock = threading.RLock()
        self._http_server = None
        self._sse_janitor_started = False

    def _generate_msg_id(self):
        """生成唯一的消息ID"""
        self.msg_id_counter += 1
        return str(int(time.time())) + str(self.msg_id_counter)

    def _generate_request_id(self):
        """生成唯一的请求ID"""
        return str(uuid.uuid4())

    def _publish_sse_event(self, request_id: str, event: dict) -> bool:
        """Append one sequenced event and wake every connected reader."""
        with self._sse_streams_lock:
            state = self.sse_streams.get(request_id)
        if state is None:
            logger.warning(
                f"[WebChannel] dropped SSE event for unknown request "
                f"{request_id}: type={event.get('type')}"
            )
            return False

        with state.condition:
            if state.closed or state.stream_complete:
                reason = "closed" if state.closed else "complete"
                logger.warning(
                    f"[WebChannel] dropped SSE event for {reason} stream "
                    f"{request_id}: type={event.get('type')}"
                )
                return False
            item = dict(event)
            item["seq"] = state.next_seq
            state.next_seq += 1
            encoded_size = len(json.dumps(
                item, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8"))
            state.events.append((item, encoded_size))
            state.total_bytes += encoded_size
            state.last_active = time.time()

            # Keep at least the newest event even if it alone exceeds the byte
            # budget. Cursor expiry is reported explicitly by stream_response.
            while len(state.events) > 1 and (
                len(state.events) > self.SSE_REPLAY_MAX_EVENTS
                or state.total_bytes > self.SSE_REPLAY_MAX_BYTES
            ):
                _, removed_size = state.events.popleft()
                state.total_bytes -= removed_size

            event_type = item.get("type")
            if event_type == "done":
                state.main_done = True
                if state.main_done_at is None:
                    state.main_done_at = state.last_active
            elif event_type == "stream_end":
                state.stream_complete = True
                state.completed_at = state.last_active
            state.condition.notify_all()
        return True

    @staticmethod
    def _session_queue_key(session_id: str, agent_id: str = None) -> str:
        from agent.registry import get_agent_registry
        registry = get_agent_registry()
        resolved = registry.get(agent_id).id
        if resolved == registry.default_agent_id:
            return session_id
        return f"{resolved}::{session_id}"

    def has_session_queue(self, session_id: str, agent_id: str = None) -> bool:
        return self._session_queue_key(session_id, agent_id) in self.session_queues

    def _fetch_latest_pair_seqs(self, session_id: str, agent_id: str = None):
        """Query the conversation store for the latest user/bot message seqs.

        Returned as ``{"user_seq": int|None, "bot_seq": int|None}``; used to
        attach seq metadata onto the SSE ``done`` event so the frontend can
        wire edit / regenerate buttons for live-streamed bubbles without a
        page refresh.
        """
        try:
            from agent.registry import get_agent_registry
            from agent.memory import get_conversation_store
            profile = get_agent_registry().get(agent_id)
            return get_conversation_store(profile.workspace).get_latest_pair_seqs(
                session_id
            )
        except Exception as e:
            logger.debug(f"[WebChannel] _fetch_latest_pair_seqs failed: {e}")
            return {"user_seq": None, "bot_seq": None}

    def send(self, reply: Reply, context: Context):
        try:
            if reply.type in self.NOT_SUPPORT_REPLYTYPE:
                logger.warning(f"Web channel doesn't support {reply.type} yet")
                return

            if reply.type == ReplyType.IMAGE_URL:
                time.sleep(0.5)

            request_id = context.get("request_id", None)
            if not request_id:
                logger.error("No request_id found in context, cannot send message")
                return

            session_id = self.request_to_session.get(request_id)
            if not session_id:
                logger.error(f"No session_id found for request {request_id}")
                return
            agent_id = context.get("agent_id") or self.request_to_agent.get(request_id)
            session_queue_key = self._session_queue_key(session_id, agent_id)

            # SSE mode: append events to the replay log.
            if request_id in self.sse_streams:
                content = reply.content if reply.content is not None else ""

                # Intermediate status lines (e.g. /install-browser phases) must NOT use "done",
                # or the frontend closes EventSource and drops subsequent events.
                if getattr(reply, "sse_phase", False):
                    self._publish_sse_event(request_id, {
                        "type": "phase",
                        "content": content,
                        "request_id": request_id,
                        "timestamp": time.time(),
                    })
                    logger.debug(f"SSE phase for request {request_id}")
                    return

                # Files are already pushed via on_event (file_to_send) during agent execution.
                # Skip duplicate file pushes here; just let the done event through.
                if reply.type in (ReplyType.IMAGE_URL, ReplyType.FILE) and content.startswith("file://"):
                    text_content = getattr(reply, 'text_content', '')
                    with self._sse_streams_lock:
                        state = self.sse_streams.get(request_id)
                    already_done = False
                    if state is not None:
                        with state.condition:
                            already_done = state.main_done
                    # A preceding TEXT reply may already have published done
                    # and deliberately left the stream open for auto-TTS. In
                    # that case this duplicate media reply must not end it.
                    if text_content and not already_done:
                        seqs = self._fetch_latest_pair_seqs(
                            session_id, context.get("agent_id")
                        )
                        published = self._publish_sse_event(request_id, {
                            "type": "done",
                            "content": text_content,
                            "request_id": request_id,
                            "timestamp": time.time(),
                            "user_seq": seqs.get("user_seq"),
                            "bot_seq": seqs.get("bot_seq"),
                        })
                        if published:
                            self._publish_sse_event(
                                request_id, {"type": "stream_end"}
                            )
                    logger.debug(f"SSE skipped duplicate file for request {request_id}")
                    return

                # Skip http-URL FILE/IMAGE_URL replies produced by chat_channel's media extraction:
                # the text reply (already sent as "done") contains the URL and the frontend will
                # render it via renderMarkdown/injectVideoPlayers, so no separate SSE event needed.
                if reply.type in (ReplyType.FILE, ReplyType.IMAGE_URL) and content.startswith(("http://", "https://")):
                    logger.debug(f"SSE skipped http media reply for request {request_id}")
                    return

                seqs = self._fetch_latest_pair_seqs(
                    session_id, context.get("agent_id")
                )
                # Absolutize workspace-relative media so images/videos the agent
                # embedded render for non-default agents too. Only affects the
                # displayed copy; TTS below still reads the original text.
                display_content = content
                if reply.type == ReplyType.TEXT and content:
                    try:
                        display_content = _rewrite_relative_media(
                            content, _get_workspace_root(session_id, agent_id)
                        )
                    except Exception as e:
                        logger.debug(f"[WebChannel] media rewrite skipped: {e}")
                self._publish_sse_event(request_id, {
                    "type": "done",
                    "content": display_content,
                    "request_id": request_id,
                    "timestamp": time.time(),
                    "user_seq": seqs.get("user_seq"),
                    "bot_seq": seqs.get("bot_seq"),
                })
                logger.debug(f"SSE done sent for request {request_id}")
                # Auto-trigger TTS once the bot finishes its text reply. The
                # synthesis runs in the background so the chat stream is never
                # blocked; the resulting audio URL is pushed via a follow-up
                # `voice_attach` SSE event and persisted to messages.extras.
                tts_pending = False
                if reply.type == ReplyType.TEXT and content.strip():
                    tts_pending = self._maybe_dispatch_auto_tts(
                        request_id, session_id, content, context
                    )
                if not tts_pending:
                    self._publish_sse_event(request_id, {"type": "stream_end"})
                return

            # Fallback: polling mode
            if session_queue_key in self.session_queues:
                content = reply.content if reply.content is not None else ""
                # Skip file:// IMAGE_URL/FILE replies originating from an SSE-enabled
                # request: they were already pushed via the `file_to_send` event during
                # agent execution. By the time the chat_channel sends the IMAGE_URL reply,
                # the SSE stream has typically closed (after the text "done") and the
                # request_id is gone from sse_streams, so we'd otherwise duplicate the file
                # as a polling bubble. Scheduler/push tasks have no on_event and must
                # still go through polling normally.
                if (
                    reply.type in (ReplyType.IMAGE_URL, ReplyType.FILE)
                    and content.startswith("file://")
                    and context.get("on_event") is not None
                ):
                    logger.debug(f"Polling skipped duplicate file reply for session {session_id}")
                    return
                # SSE-enabled requests already stream the text reply to the
                # client. Do NOT also enqueue it for polling: if the user
                # switched away mid-run, the queued copy would resurface as a
                # duplicate bubble when they return and poll the session.
                if reply.type == ReplyType.TEXT and context.get("on_event") is not None:
                    logger.debug(f"Polling skipped SSE text reply for session {session_id}")
                    return
                if reply.type == ReplyType.TEXT and content:
                    try:
                        content = _rewrite_relative_media(
                            content, _get_workspace_root(session_id, agent_id)
                        )
                    except Exception as e:
                        logger.debug(f"[WebChannel] media rewrite skipped: {e}")
                response_data = {
                    "type": str(reply.type),
                    "content": content,
                    "timestamp": time.time(),
                    "request_id": request_id
                }
                self.session_queues[session_queue_key].put(response_data)
                logger.debug(f"Response sent to poll queue for session {session_id}, request {request_id}")
            else:
                logger.warning(f"No response queue found for session {session_id}, response dropped")

        except Exception as e:
            logger.error(f"Error in send method: {e}")

    def _make_sse_callback(self, request_id: str):
        """Build a callback that publishes agent events to the SSE replay log."""

        # Cap reasoning bytes pushed to the frontend per request to avoid
        # browser stalls / crashes on very long chains-of-thought. Anything
        # beyond the cap is dropped from the stream (DB still persists a
        # truncated copy via _truncate_reasoning_for_storage).
        # Keep aligned with frontend REASONING_RENDER_CAP and backend
        # MAX_STORED_REASONING_CHARS.
        MAX_REASONING_STREAM_CHARS = 4 * 1024  # 4 KB
        # A tool's human-readable outcome (ToolResult.display). Reasoning is a
        # trace worth capping hard; this is the deliverable, so it gets room.
        MAX_DISPLAY_STREAM_CHARS = 32 * 1024
        # Use a single-element list as a mutable counter accessible from closure.
        reasoning_chars_sent = [0]
        reasoning_capped_notified = [False]
        # Captures the first error message emitted by agent_stream so the
        # subsequent agent_end handler can skip its "empty final_response"
        # fallback (which would otherwise overwrite the real error).
        streamed_error: List[str] = []

        def on_event(event: dict):
            if request_id not in self.sse_streams:
                return
            publish = lambda item: self._publish_sse_event(request_id, item)
            event_type = event.get("type")
            data = event.get("data", {})

            if event_type == "reasoning_update":
                delta = data.get("delta", "")
                if not delta:
                    return
                remaining = MAX_REASONING_STREAM_CHARS - reasoning_chars_sent[0]
                if remaining <= 0:
                    if not reasoning_capped_notified[0]:
                        reasoning_capped_notified[0] = True
                        publish({
                            "type": "reasoning",
                            "content": "\n\n... [reasoning truncated for display] ...",
                        })
                    return
                if len(delta) > remaining:
                    delta = delta[:remaining]
                reasoning_chars_sent[0] += len(delta)
                publish({"type": "reasoning", "content": delta})

            elif event_type == "message_update":
                delta = data.get("delta", "")
                if delta:
                    publish({"type": "delta", "content": delta})

            elif event_type == "peer_message_start":
                # A teammate takes over for a stretch of this turn. What follows
                # is its reply, in the same event types as any other, until the
                # matching end marker hands the floor back.
                publish({
                    "type": "peer_start",
                    "card_id": data.get("card_id"),
                    "agent_id": data.get("agent_id"),
                    "agent_name": data.get("agent_name"),
                    "source_id": data.get("source_id"),
                    "source_name": data.get("source_name"),
                })

            elif event_type == "peer_message_end":
                publish({
                    "type": "peer_end",
                    "card_id": data.get("card_id"),
                    "agent_id": data.get("agent_id"),
                    "status": data.get("status", "done"),
                })

            elif event_type == "tool_retrieval":
                # Additive MCP retrieval diagnostics. Forward only the
                # allowlisted, already-sanitized fields (query text/vectors are
                # never included by the emitter and must never reach the client).
                payload = {"type": "tool_retrieval"}
                for key in (
                    "mode", "total_mcp_tools", "selected_mcp_tools",
                    "builtin_tools", "top_k", "candidate_count",
                    "selected_tools", "ranked_tools", "fallback_reason",
                ):
                    if key in data:
                        payload[key] = data[key]
                publish(payload)

            elif event_type == "tool_execution_start":
                tool_name = data.get("tool_name", "tool")
                arguments = data.get("arguments", {})
                publish({"type": "tool_start", "tool_call_id": data.get("tool_call_id"), "tool": tool_name, "arguments": arguments})

            elif event_type == "tool_execution_progress":
                publish({
                    "type": "tool_progress",
                    "tool_call_id": data.get("tool_call_id"),
                    "tool": data.get("tool_name", "tool"),
                    "content": str(data.get("message", ""))[-4 * 1024:],
                })

            elif event_type == "tool_execution_end":
                tool_name = data.get("tool_name", "tool")
                status = data.get("status", "success")
                result = data.get("result", "")
                exec_time = data.get("execution_time", 0)
                # Truncate long results to avoid huge SSE payloads
                result_str = str(result)
                if len(result_str) > 2000:
                    result_str = result_str[:2000] + "…"
                payload = {
                    "type": "tool_end",
                    "tool_call_id": data.get("tool_call_id"),
                    "tool": tool_name,
                    "status": status,
                    "result": result_str,
                    "execution_time": round(exec_time, 2)
                }
                # Carry the permission-refusal marker so the UI can offer a
                # one-click "switch permission" hint rather than a generic error.
                if data.get("permission_denied"):
                    payload["permission_denied"] = True
                    payload["permission_mode"] = data.get("permission_mode")
                # A tool that wrote its outcome for a person sends that
                # instead. It gets a far larger budget than `result`: this is
                # the report itself, not a trace of how it was produced.
                display = data.get("display")
                if display:
                    display = str(display)
                    if len(display) > MAX_DISPLAY_STREAM_CHARS:
                        display = display[:MAX_DISPLAY_STREAM_CHARS] + "…"
                    payload["display"] = display
                publish(payload)

            elif event_type == "subagent_step":
                # A tool call made by a sub agent, relayed so the card for
                # that sub agent can show what it is doing instead of
                # spinning for minutes.
                publish({
                    "type": "subagent_step",
                    "card_id": data.get("card_id"),
                    "step_id": data.get("step_id"),
                    "phase": data.get("phase"),
                    "tool": data.get("tool_name", "tool"),
                    "arguments": data.get("arguments") or {},
                    "status": data.get("status"),
                    "error": data.get("error"),
                    "execution_time": data.get("execution_time", 0),
                })

            elif event_type == "message_end":
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    publish({"type": "message_end", "has_tool_calls": True})

            elif event_type == "error":
                # Agent raised an exception (LLM 401/timeout/etc). Surface the
                # real message instead of letting the empty-response fallback
                # below hide it as "(模型未返回任何内容)".
                err_msg = data.get("error") or "unknown error"
                logger.warning(
                    f"[WebChannel] agent_stream emitted error for "
                    f"request {request_id}: {err_msg}"
                )
                # Remember it so the agent_end handler below knows not to
                # rewrite the message into a generic empty-response notice.
                streamed_error.append(err_msg)
                publish({
                    "type": "done",
                    "content": f"❌ {err_msg}",
                    "request_id": request_id,
                    "timestamp": time.time(),
                })
                publish({"type": "stream_end"})

            elif event_type == "agent_cancelled":
                # Push an explicit cancelled SSE event so the frontend
                # marks the bubble as stopped. A trailing "done" still
                # arrives with the partial answer.
                final_response = data.get("final_response", "")
                publish({
                    "type": "cancelled",
                    "content": final_response,
                    "request_id": request_id,
                    "timestamp": time.time(),
                })

            elif event_type == "agent_end":
                # Safety net: if the agent finishes with an empty final_response,
                # chat_channel skips _send_reply (because reply.content is empty),
                # which means no "done" event is ever emitted and the SSE stream
                # would hang until the 10-min idle timeout. Push a fallback "done"
                # here so the frontend always gets closure.
                final_response = data.get("final_response", "")
                if not final_response or not str(final_response).strip():
                    if streamed_error:
                        # Error was already surfaced via the `error` event
                        # handler above; nothing more to do here.
                        pass
                    else:
                        logger.warning(
                            f"[WebChannel] agent_end with empty final_response for "
                            f"request {request_id}, sending fallback done"
                        )
                        publish({
                            "type": "done",
                            "content": i18n.t(
                                "(模型未返回任何内容，请重试或换一种方式描述你的需求)",
                                "(The model returned no content. Please retry or rephrase your request.)",
                            ),
                            "request_id": request_id,
                            "timestamp": time.time(),
                        })
                        publish({"type": "stream_end"})

            elif event_type == "file_to_send":
                file_path = data.get("path", "")
                file_name = data.get("file_name", os.path.basename(file_path))
                file_type = data.get("file_type", "file")
                # Remote URLs are passed through as-is; local files are served
                # via the backend /api/file endpoint.
                remote_url = data.get("url", "")
                is_remote = bool(remote_url) and remote_url.lower().startswith(("http://", "https://"))
                if is_remote:
                    web_url = remote_url
                else:
                    from urllib.parse import quote
                    web_url = f"/api/file?path={quote(file_path)}"
                is_image = file_type == "image"
                payload = {
                    "type": "image" if is_image else "file",
                    "content": web_url,
                    "file_name": file_name,
                    # Preserve the concrete media kind (image/video/audio/...)
                    # so richer clients can render an inline player.
                    "file_type": file_type,
                }
                # Expose the local absolute path so the desktop client can open
                # the file directly (Finder / default app) instead of the browser.
                if not is_remote and file_path:
                    payload["abs_path"] = file_path
                publish(payload)

            elif event_type == "artifact":
                payload = _build_artifact_payload(data)
                if payload:
                    publish(payload)

            elif event_type in ("agent_start", "turn_end"):
                self._mark_stored_point(request_id, advance_only=event_type == "turn_end")

        return on_event

    def _mark_stored_point(self, request_id: str, advance_only: bool) -> None:
        """Record where the stored transcript and the event log line up.

        The run starts after its query is stored, and each step is stored
        before turn_end is announced, so at either moment the newest stored
        message and the newest event describe the same point. A step that did
        not get stored leaves the transcript where it was; the earlier mark
        then stays, rather than one that would skip the missing step.
        """
        with self._sse_streams_lock:
            state = self.sse_streams.get(request_id)
        session_id = self.request_to_session.get(request_id)
        if state is None or not session_id:
            return
        try:
            from agent.registry import get_agent_registry
            from agent.memory import get_conversation_store
            profile = get_agent_registry().get(self.request_to_agent.get(request_id))
            stored_seq = get_conversation_store(profile.workspace).latest_seq(session_id)
        except Exception as e:
            logger.debug(f"[WebChannel] stored point skipped for {request_id}: {e}")
            return
        if stored_seq is None:
            return
        with state.condition:
            if advance_only and state.stored_seq is not None and stored_seq <= state.stored_seq:
                return
            state.stored_seq = stored_seq
            state.stored_event_seq = state.next_seq - 1

    def resumable_stream(self, session_id: str, agent_id: str = None) -> Optional[dict]:
        """The unfinished reply a session is streaming, for a page loaded mid-reply.

        Returns ``{"request_id", "stored_seq", "after_seq"}``: render the
        transcript up to ``stored_seq`` and follow the stream after
        ``after_seq``. ``stored_seq`` is None before the run has started, when
        nothing of the reply is stored and the whole stream is to follow.
        None when nothing is in flight.
        """
        try:
            from agent.registry import get_agent_registry
            owner = get_agent_registry().get(agent_id).id
        except Exception:
            owner = agent_id
        for request_id, sid in reversed(list(self.request_to_session.items())):
            if sid != session_id or self.request_to_agent.get(request_id) != owner:
                continue
            with self._sse_streams_lock:
                state = self.sse_streams.get(request_id)
            if state is None:
                continue
            with state.condition:
                if state.closed or state.main_done or state.stream_complete:
                    return None
                return {
                    "request_id": request_id,
                    "stored_seq": state.stored_seq,
                    "after_seq": state.stored_event_seq,
                }
        return None

    # ------------------------------------------------------------------
    # TTS auto-dispatch
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_voice_reply_mode() -> str:
        """
        Decide the TTS auto-reply policy.

        Source of truth is the cross-channel pair
        (`always_reply_voice`, `voice_reply_voice`) which chat_channel
        also consults. The web UI presents these as a single three-state
        picker (off / voice_if_voice / always) via a lossless mapping.
        """
        if conf().get("always_reply_voice", False):
            return "always"
        if conf().get("voice_reply_voice", False):
            return "voice_if_voice"
        return "off"

    # Mirror of ModelsHandler._TTS_PROVIDERS. zhipu is intentionally omitted
    # from the UI (GLM-TTS prelude beep); pinning it in config.json still works.
    _TTS_PROVIDERS_SUGGEST_ORDER = ["openai", "minimax", "dashscope", "linkai"]

    @classmethod
    def _tts_provider_ready(cls) -> bool:
        """True if user picked a provider OR any suggested vendor has an API key."""
        if (conf().get("text_to_voice") or "").strip():
            return True
        for pid in cls._TTS_PROVIDERS_SUGGEST_ORDER:
            meta = providers.PROVIDER_MODELS.get(pid) or {}
            key_field = meta.get("api_key_field")
            if not key_field:
                continue
            val = (conf().get(key_field) or "").strip()
            if val and val not in ("YOUR API KEY", "YOUR_API_KEY"):
                return True
        return False

    def _maybe_dispatch_auto_tts(
        self,
        request_id: str,
        session_id: str,
        text: str,
        context: dict,
    ) -> bool:
        try:
            mode = self._resolve_voice_reply_mode()
            if mode == "off":
                return False
            if mode == "voice_if_voice" and not context.get("is_voice_input"):
                return False
            if not self._tts_provider_ready():
                return False
            threading.Thread(
                target=self._synthesize_tts_async,
                args=(request_id, session_id, text, context.get("agent_id")),
                daemon=True,
            ).start()
            return True
        except Exception as e:
            logger.debug(f"[WebChannel] auto-tts dispatch skipped: {e}")
            return False

    def _synthesize_tts_async(
        self,
        request_id: str,
        session_id: str,
        text: str,
        agent_id: str = None,
    ) -> None:
        try:
            from bridge.bridge import Bridge
            reply = Bridge().fetch_text_to_voice(text)
            if reply is None or reply.type != ReplyType.VOICE or not reply.content:
                logger.warning(
                    f"[WebChannel] TTS produced no audio for request {request_id}: "
                    f"reply={reply}"
                )
                return
            url = self._publish_tts_audio(reply.content, agent_id)
            if not url:
                logger.warning(f"[WebChannel] TTS publish failed for request {request_id}")
                return
            payload = {"audio": {"url": url, "kind": "tts"}}
            try:
                from agent.memory import get_conversation_store
                from agent.registry import get_agent_registry
                profile = get_agent_registry().get(agent_id)
                get_conversation_store(
                    profile.workspace
                ).attach_extras_to_last_assistant(session_id, payload)
            except Exception as e:
                logger.debug(f"[WebChannel] tts persist skipped: {e}")
            if request_id not in self.sse_streams:
                logger.warning(
                    f"[WebChannel] TTS ready but SSE stream already closed "
                    f"for request {request_id} (url={url})"
                )
                return
            self._publish_sse_event(request_id, {
                "type": "voice_attach",
                "url": url,
                "request_id": request_id,
                "timestamp": time.time(),
            })
            logger.info(f"[WebChannel] TTS voice_attach pushed for request {request_id}: {url}")
        except Exception as e:
            # TTS failures are intentionally silent (no user-facing error).
            logger.warning(f"[WebChannel] TTS synthesis failed: {e}")
        finally:
            self._publish_sse_event(request_id, {"type": "stream_end"})

    @staticmethod
    def _publish_tts_audio(src_path: str, agent_id: str = None) -> str:
        """Move a TTS file into uploads/ and return its public URL."""
        try:
            if not src_path or not os.path.isfile(src_path):
                logger.warning(f"[WebChannel] publish_tts_audio missing source: {src_path!r}")
                return ""
            ext = os.path.splitext(src_path)[1].lower() or ".mp3"
            upload_dir = _get_upload_dir(agent_id)
            os.makedirs(upload_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            dst_name = f"voice_reply_{ts}_{random.randint(0, 9999)}{ext}"
            dst_path = os.path.join(upload_dir, dst_name)
            shutil.move(src_path, dst_path)
            logger.debug(f"[WebChannel] publish_tts_audio moved {src_path} -> {dst_path}")
            suffix = f"?agent_id={agent_id}" if agent_id else ""
            return f"/uploads/{dst_name}{suffix}"
        except Exception as e:
            logger.warning(f"[WebChannel] publish_tts_audio failed: {e}")
            return ""

    @staticmethod
    def _cleanup_stale_voice_recordings(max_age_seconds: int = 3600) -> None:
        """Drop voice_input_* uploads older than max_age_seconds (run at startup)."""
        try:
            upload_dir = _get_upload_dir()
            if not os.path.isdir(upload_dir):
                return
            now = time.time()
            removed = 0
            for name in os.listdir(upload_dir):
                if not name.startswith("voice_input_"):
                    continue
                full = os.path.join(upload_dir, name)
                try:
                    if not os.path.isfile(full):
                        continue
                    if now - os.path.getmtime(full) > max_age_seconds:
                        os.remove(full)
                        removed += 1
                except OSError:
                    continue
            if removed:
                logger.info(f"[WebChannel] cleaned up {removed} stale voice recording(s) from {upload_dir}")
        except Exception as e:
            logger.warning(f"[WebChannel] voice cleanup failed: {e}")

    def upload_file(self):
        """Handle file or directory upload via multipart/form-data.

        A JSON body ({"local_path": ...}) instead selects the desktop-only
        import-by-path route, see `_import_local_file`.
        """

        def _reject(message):
            logger.warning("[WebChannel] Upload rejected: %s", message)
            return json.dumps({"status": "error", "message": message})

        content_type = (web.ctx.env.get("CONTENT_TYPE") or "").lower()
        if content_type.startswith("application/json"):
            return self._import_local_file(_reject)

        try:
            # Trace the request on arrival: it is the only way to tell a client
            # that never sent anything (file picker / drag-drop broken) apart
            # from a request the backend rejected.
            logger.info(
                "[WebChannel] Upload request received: %s bytes, content-type=%s",
                web.ctx.env.get("CONTENT_LENGTH") or "?",
                web.ctx.env.get("CONTENT_TYPE") or "?",
            )
            params = _raw_web_input()
            file_obj = params.get("file")
            file_objs = params.get("files")
            relative_path = params.get("relative_path", "")
            relative_paths = params.get("relative_paths")
            upload_id = params.get("upload_id", "")

            directory_files = _ensure_list(file_objs)

            # NOTE: cgi.FieldStorage raises TypeError on truthy checks for single-file
            # uploads (Python 3.9+). Always use `is not None` instead of `if file_obj`.
            if not directory_files and file_obj is not None and relative_path:
                directory_files = [file_obj]

            directory_rel_paths = _ensure_list(relative_paths)

            if not directory_rel_paths and relative_path:
                directory_rel_paths = [relative_path]

            is_directory_upload = bool(directory_files) or bool(directory_rel_paths) or bool(relative_path) or bool(upload_id)

            # Multipart uploads carry the agent in the query string only: the
            # client deliberately keeps it out of the form body (a field in
            # both arrives as a list and breaks handlers), and rawinput("post")
            # parses the body alone.
            agent_id = _scoped_agent_id(params)

            upload_dir = _get_upload_dir(agent_id)
            if is_directory_upload:
                if not upload_id:
                    return _reject("Missing upload_id for directory upload")
                if not directory_files:
                    return _reject("No files uploaded")
                if len(directory_files) != len(directory_rel_paths):
                    return _reject("Directory upload payload mismatch")

                safe_upload_id = _sanitize_upload_id(upload_id)
                upload_root = os.path.join(upload_dir, f"webdir_{safe_upload_id}")
                upload_root_real = os.path.realpath(upload_root)

                root_name = None
                saved_files = 0
                for file_obj, rel_path in zip(directory_files, directory_rel_paths):
                    if file_obj is None:
                        raise ValueError("Invalid uploaded file")
                    safe_rel_path, save_path = _resolve_upload_path(upload_root_real, rel_path)
                    current_root_name = safe_rel_path.split("/", 1)[0]
                    if root_name is None:
                        root_name = current_root_name
                    elif root_name != current_root_name:
                        raise ValueError("Directory upload must use a single root folder")
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    content_bytes = _read_uploaded_file_bytes(file_obj)
                    with open(save_path, "wb") as f:
                        f.write(content_bytes)
                    saved_files += 1

                if not root_name:
                    raise ValueError("Directory root path missing")

                root_path = os.path.realpath(os.path.join(upload_root_real, root_name))
                if not _is_within_directory(upload_root_real, root_path):
                    raise ValueError("Invalid directory upload path")

                logger.info(f"[WebChannel] Directory uploaded: {root_name} -> {root_path} ({saved_files} files)")
                return json.dumps({
                    "status": "success",
                    "file_path": root_path,
                    "file_name": root_name,
                    "file_type": "directory",
                    "file_count": saved_files,
                    "root_path": root_path,
                    "root_name": root_name,
                    "upload_type": "directory",
                }, ensure_ascii=False)

            if file_obj is None or not hasattr(file_obj, "filename") or not file_obj.filename:
                return _reject(f"No file uploaded (form fields: {sorted(params.keys())})")

            original_name = file_obj.filename
            ext = os.path.splitext(original_name)[1].lower()
            safe_name = f"web_{uuid.uuid4().hex[:8]}{ext}"
            save_path = os.path.join(upload_dir, safe_name)
            public_path = safe_name
            display_name = original_name

            content_bytes = _read_uploaded_file_bytes(file_obj)
            with open(save_path, "wb") as f:
                f.write(content_bytes)

            if ext in IMAGE_EXTENSIONS:
                file_type = "image"
            elif ext in VIDEO_EXTENSIONS:
                file_type = "video"
            else:
                file_type = "file"

            from urllib.parse import quote
            # Uploads land in the agent's own workspace, so the URL has to name
            # the agent: without it /uploads/ resolves against the default
            # agent's tmp and every non-default agent's preview 404s.
            suffix = f"?agent_id={quote(str(agent_id), safe='')}" if agent_id else ""
            preview_url = f"/uploads/{quote(public_path, safe='/')}{suffix}"

            logger.info(f"[WebChannel] File uploaded: {original_name} -> {save_path} ({file_type})")

            return json.dumps({
                "status": "success",
                "file_path": save_path,
                "file_name": display_name,
                "file_type": file_type,
                "preview_url": preview_url,
            }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"[WebChannel] File upload error: {e}", exc_info=True)
            return json.dumps({"status": "error", "message": str(e)})

    def _import_local_file(self, _reject):
        """Attach a file that already sits on this machine, by path.

        The desktop client and its backend share a filesystem, so pushing the
        bytes through an HTTP multipart body only adds a place to fail: the
        renderer's network stack, keep-alive sockets shared with SSE streams,
        and on Windows security software proxying localhost traffic all produced
        intermittent "Failed to fetch" errors that looked like a dead backend.
        Copying the file directly has none of those moving parts.

        Only the desktop shell may use this: the request must originate on the
        loopback interface and carry the per-launch token the shell passed to
        this process. Anyone else (including a browser on the same machine)
        gets a plain error and falls back to the multipart route.
        """
        try:
            payload = json.loads(web.data() or b"{}")
        except (ValueError, TypeError):
            return _reject("Invalid JSON body")
        if not isinstance(payload, dict):
            return _reject("Invalid JSON body")

        local_path = str(payload.get("local_path") or "").strip()
        if not local_path:
            return _reject("local_path is required")

        if not (_is_loopback_request() and _desktop_token_matches()):
            return _reject("Import by path is only available to the desktop client")

        if not os.path.isabs(local_path):
            return _reject("local_path must be absolute")
        real_path = os.path.realpath(local_path)
        if not os.path.isfile(real_path):
            return _reject("File not found")
        size = os.path.getsize(real_path)
        if size > MAX_LOCAL_IMPORT_BYTES:
            return _reject("File too large")

        agent_id = _scoped_agent_id(payload)

        try:
            upload_dir = _get_upload_dir(agent_id)
            original_name = os.path.basename(local_path)
            ext = os.path.splitext(original_name)[1].lower()
            safe_name = f"web_{uuid.uuid4().hex[:8]}{ext}"
            save_path = os.path.join(upload_dir, safe_name)
            shutil.copyfile(real_path, save_path)

            if ext in IMAGE_EXTENSIONS:
                file_type = "image"
            elif ext in VIDEO_EXTENSIONS:
                file_type = "video"
            else:
                file_type = "file"

            logger.info(
                f"[WebChannel] File imported by path: {original_name} -> {save_path} ({file_type}, {size} bytes)"
            )
            suffix = f"?agent_id={quote(str(agent_id), safe='')}" if agent_id else ""
            return json.dumps({
                "status": "success",
                "file_path": save_path,
                "file_name": original_name,
                "file_type": file_type,
                "preview_url": f"/uploads/{quote(safe_name, safe='/')}{suffix}",
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Local file import error: {e}", exc_info=True)
            return json.dumps({"status": "error", "message": str(e)})

    def post_message(self):
        """
        Handle incoming messages from users via POST request.
        Returns a request_id for tracking this specific request.
        Supports optional attachments (file paths from /upload).
        """
        try:
            data = web.data()
            json_data = json.loads(data)
            session_id = json_data.get('session_id', f'session_{int(time.time())}')
            from bridge.bridge import Bridge
            agent_bridge = Bridge().get_agent_bridge()
            resolved_agent_id = agent_bridge.agent_router.resolve(
                explicit_agent_id=json_data.get("agent_id"),
            )
            prompt = json_data.get('message', '')
            # Kept before any prefixing or attachment lines, so mention parsing
            # still sees what the user actually typed.
            typed_prompt = prompt
            use_sse = json_data.get('stream', True)
            attachments = json_data.get('attachments', [])
            # Tag the message as originating from voice input so the post-reply
            # TTS hook can honour the `voice_if_voice` policy (mirrors the
            # desire_rtype concept used by other channels).
            is_voice_input = bool(json_data.get('is_voice', False))

            # Fast path for /cancel: bypass the session queue and SSE setup.
            # Web frontend (stream=true) only listens to SSE, so we return an
            # inline_reply payload to be rendered synchronously.
            stripped_prompt = (prompt or "").strip().lower()
            if stripped_prompt == "/cancel":
                from agent.protocol import get_cancel_registry
                scoped_session_id = agent_bridge._cancel_key(
                    resolved_agent_id,
                    session_id,
                    agent_bridge.agent_registry.default_agent_id,
                )
                cancelled = get_cancel_registry().cancel_session(scoped_session_id)
                lang = (json_data.get('lang') or 'zh').lower()
                msg_text = _cancel_reply_text(cancelled, lang)
                logger.info(
                    f"[WebChannel] /cancel fast-path: session={session_id}, cancelled={cancelled}, lang={lang}"
                )
                return json.dumps({
                    "status": "success",
                    "request_id": "",
                    "stream": False,
                    "inline_reply": msg_text,
                })

            # Explicit steering also bypasses the normal session queue. The
            # Web button sends ``steer: true`` with raw input; typed /steer
            # commands use the same endpoint and semantics as IM channels.
            steer_requested = bool(json_data.get("steer", False))
            is_steer_command = (
                re.match(r"^/steer(?:\s|$)", stripped_prompt) is not None
            )
            if steer_requested or is_steer_command:
                instruction = (
                    (prompt or "").strip()[len("/steer"):].strip()
                    if is_steer_command
                    else (prompt or "").strip()
                )
                result = agent_bridge.steer_session(
                    session_id, instruction, resolved_agent_id
                )
                lang = (json_data.get("lang") or "zh").lower()
                msg_text = _steer_reply_text(result.status, lang)
                logger.info(
                    f"[WebChannel] steer fast-path: session={session_id}, "
                    f"status={result.status.value}, lang={lang}"
                )
                return json.dumps({
                    "status": "success",
                    "request_id": "",
                    "stream": False,
                    "steered": result.accepted,
                    "inline_reply": msg_text,
                }, ensure_ascii=False)

            # Append file references to the prompt (same format as QQ channel)
            if attachments:
                file_refs = []
                for att in attachments:
                    ftype = att.get("file_type", "file")
                    fpath = att.get("file_path", "")
                    if not fpath:
                        continue
                    if ftype == "workspace_ref":
                        # Already lives in the workspace (dragged from the file panel
                        # or picked with @); reference it in place so the agent opens
                        # the original instead of an uploaded copy. Naming the kind
                        # tells the agent whether to `read` it or `ls` into it.
                        # Resolve relative to the session's working root (project
                        # dir when opened, else the workspace).
                        is_dir = os.path.isdir(
                            os.path.join(
                                _get_workspace_root(session_id, resolved_agent_id), fpath
                            )
                        )
                        label = (
                            i18n.t('工作空间目录', 'Workspace directory') if is_dir
                            else i18n.t('工作空间文件', 'Workspace file')
                        )
                        file_refs.append(f"[{label}: {fpath}]")
                    elif ftype == "image":
                        file_refs.append(f"[{i18n.t('图片', 'Image')}: {fpath}]")
                    elif ftype == "video":
                        file_refs.append(f"[{i18n.t('视频', 'Video')}: {fpath}]")
                    elif ftype == "directory":
                        file_refs.append(f"[{i18n.t('目录', 'Directory')}: {fpath}]")
                    else:
                        file_refs.append(f"[{i18n.t('文件', 'File')}: {fpath}]")
                if file_refs:
                    prompt = prompt + "\n" + "\n".join(file_refs)
                    logger.info(f"[WebChannel] Attached {len(file_refs)} file(s) to message")

            request_id = self._generate_request_id()
            self.request_to_session[request_id] = session_id
            self.request_to_agent[request_id] = resolved_agent_id

            session_queue_key = self._session_queue_key(
                session_id, resolved_agent_id
            )
            if session_queue_key not in self.session_queues:
                self.session_queues[session_queue_key] = Queue()

            if use_sse:
                with self._sse_streams_lock:
                    self.sse_streams[request_id] = SSEStreamState()

            trigger_prefixs = conf().get("single_chat_prefix", [""])
            if check_prefix(prompt, trigger_prefixs) is None:
                if trigger_prefixs:
                    prompt = trigger_prefixs[0] + prompt
                    logger.debug(f"[WebChannel] Added prefix to message: {prompt}")

            msg = WebMessage(self._generate_msg_id(), prompt)
            msg.from_user_id = session_id

            context = self._compose_context(ContextType.TEXT, prompt, msg=msg, isgroup=False)

            if context is None:
                logger.warning(f"[WebChannel] Context is None for session {session_id}, message may be filtered")
                self._drop_sse_request(request_id)
                return json.dumps({"status": "error", "message": "Message was filtered"})

            context["session_id"] = session_id
            context["receiver"] = session_id
            context["request_id"] = request_id
            context["agent_id"] = resolved_agent_id
            # Addressing a teammate hands them the turn. The conversation still
            # belongs to `resolved_agent_id`, so this only changes who answers.
            # The composer already knows who it wrote; parsing the text is the
            # fallback for a mention typed by hand or replayed from history.
            roster = _session_roster(session_id, resolved_agent_id)
            addressed = (json_data.get("speaker_agent_id") or "").strip()
            if not addressed or not any(item["id"] == addressed for item in roster):
                addressed = _addressed_agent_id(typed_prompt, roster)
            if addressed and addressed != resolved_agent_id:
                context["speaker_agent_id"] = addressed
            if is_voice_input:
                # Web channel runs its own TTS post-pipeline via
                # _maybe_dispatch_auto_tts; don't set desire_rtype here or
                # chat_channel would synthesize a duplicate VOICE reply.
                context["is_voice_input"] = True

            if use_sse:
                context["on_event"] = self._make_sse_callback(request_id)

            threading.Thread(target=self.produce, args=(context,)).start()

            return json.dumps({
                "status": "success",
                "request_id": request_id,
                "stream": use_sse,
                # Lets the live bubble carry the right name and face while the
                # reply streams, before any of it has been persisted.
                "speaker": context.get("speaker_agent_id") or "",
            })

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def _drop_sse_request(self, request_id: str):
        """Reclaim all state tied to an SSE request."""
        with self._sse_streams_lock:
            state = self.sse_streams.pop(request_id, None)
            self.request_to_session.pop(request_id, None)
            self.request_to_agent.pop(request_id, None)
        if state is not None:
            with state.condition:
                state.closed = True
                state.condition.notify_all()

    def _sweep_sse_streams(self, now: Optional[float] = None) -> int:
        """Finalize overdue tails and reclaim expired SSE replay logs."""
        now = time.time() if now is None else now
        with self._sse_streams_lock:
            states = list(self.sse_streams.items())

        overdue = []
        for request_id, state in states:
            with state.condition:
                if (
                    state.main_done
                    and not state.stream_complete
                    and state.main_done_at is not None
                    and now - state.main_done_at
                    >= self.SSE_POST_DONE_TAIL_SECONDS
                ):
                    overdue.append(request_id)
        for request_id in overdue:
            self._publish_sse_event(request_id, {"type": "stream_end"})

        with self._sse_streams_lock:
            states = list(self.sse_streams.items())
        stale = []
        for request_id, state in states:
            with state.condition:
                if state.stream_complete and state.completed_at is not None:
                    expired = (
                        now - state.completed_at
                        >= self.SSE_COMPLETED_TTL_SECONDS
                    )
                else:
                    expired = (
                        now - state.last_active
                        >= self.SSE_IDLE_TIMEOUT_SECONDS
                    )
            if expired:
                stale.append(request_id)

        for request_id in stale:
            self._drop_sse_request(request_id)
        return len(stale)

    def _start_sse_janitor(self):
        """Start a background thread that reclaims orphaned SSE logs.

        Completed logs remain replayable for a short grace period. Abandoned
        unfinished logs use the longer idle timeout.
        """
        if self._sse_janitor_started:
            return
        self._sse_janitor_started = True

        SWEEP_INTERVAL = 60

        def _sweep():
            while True:
                time.sleep(SWEEP_INTERVAL)
                try:
                    reclaimed = self._sweep_sse_streams()
                    if reclaimed:
                        logger.info(
                            f"[WebChannel] SSE janitor reclaimed {reclaimed} "
                            f"idle stream(s)"
                        )
                except Exception as e:
                    logger.warning(f"[WebChannel] SSE janitor error: {e}")

        t = threading.Thread(target=_sweep, name="sse-janitor", daemon=True)
        t.start()

    def stream_response(self, request_id: str, after_seq: int = 0):
        """
        SSE generator for a given request_id.
        Yields UTF-8 encoded bytes to avoid WSGI Latin-1 mangling.
        Each connection reads the request's event log using its own cursor.
        """
        with self._sse_streams_lock:
            state = self.sse_streams.get(request_id)
        if state is None:
            # Logs live in memory only, so a restart forgets every request the
            # previous process was streaming. The reason lets the client say so
            # instead of reporting a generic send failure.
            yield (
                b"data: {\"type\": \"error\", \"message\": \"invalid request_id\", "
                b"\"reason\": \"unknown_request\"}\n\n"
            )
            return
        try:
            cursor = max(0, int(after_seq))
        except (TypeError, ValueError):
            cursor = 0
        idle_timeout = 600  # 10 minutes without any real event
        deadline = time.time() + idle_timeout
        # A cancel only takes effect at the agent's next checkpoint, so the run
        # keeps emitting events (tool results, the partial reply) for a while
        # after the user presses Stop. Stay open for them, just not for the
        # full idle timeout.
        CANCEL_GRACE_SECONDS = 60
        cancelled = False

        try:
            while time.time() < deadline:
                resync_payload = None
                force_stream_end = False
                with state.condition:
                    now = time.time()
                    state.last_active = now
                    force_stream_end = (
                        state.main_done
                        and not state.stream_complete
                        and state.main_done_at is not None
                        and now - state.main_done_at
                        >= self.SSE_POST_DONE_TAIL_SECONDS
                    )
                    if state.events:
                        first_seq = state.events[0][0]["seq"]
                        latest_seq = state.events[-1][0]["seq"]
                        if cursor < first_seq - 1:
                            resync_payload = {
                                "type": "resync_required",
                                "reason": "event_cursor_expired",
                                "after_seq": cursor,
                                "first_available_seq": first_seq,
                            }
                        elif cursor > latest_seq:
                            resync_payload = {
                                "type": "resync_required",
                                "reason": "event_cursor_ahead",
                                "after_seq": cursor,
                                "latest_available_seq": latest_seq,
                            }
                    pending = [
                        event for event, _ in state.events
                        if event["seq"] > cursor
                    ]
                    complete = state.stream_complete
                    closed = state.closed
                    if (
                        resync_payload is None
                        and not pending and not complete and not closed
                    ):
                        state.condition.wait(timeout=1)

                if force_stream_end:
                    self._publish_sse_event(
                        request_id, {"type": "stream_end"}
                    )
                    continue

                if resync_payload is not None:
                    payload = json.dumps(resync_payload, ensure_ascii=False)
                    yield f"data: {payload}\n\n".encode("utf-8")
                    return

                if not pending:
                    if complete or closed:
                        break
                    yield b": keepalive\n\n"
                    continue

                for item in pending:
                    deadline = time.time() + (
                        CANCEL_GRACE_SECONDS if cancelled else idle_timeout
                    )
                    payload = json.dumps(item, ensure_ascii=False)
                    yield (
                        f"id: {item['seq']}\n"
                        f"data: {payload}\n\n"
                    ).encode("utf-8")
                    cursor = item["seq"]
                    if item.get("type") == "cancelled":
                        cancelled = True
                        deadline = time.time() + CANCEL_GRACE_SECONDS
                    if item.get("type") == "stream_end":
                        return
        except GeneratorExit:
            # The event log is deliberately retained for reconnection.
            raise

    def cancel_request(self):
        """
        Cancel an in-flight agent run.

        Body: {"request_id": "...", "session_id": "..."}
        Either field is sufficient; request_id is preferred when known.
        Always returns success even when nothing was running, so the
        client's UX is idempotent.
        """
        try:
            from agent.protocol import get_cancel_registry

            data = web.data()
            try:
                json_data = json.loads(data) if data else {}
            except Exception:
                json_data = {}

            request_id = (json_data.get("request_id") or "").strip()
            session_id = (json_data.get("session_id") or "").strip()
            lang = (json_data.get("lang") or "zh").lower()
            from bridge.bridge import Bridge
            from agent.routing import AgentUnavailableError
            agent_bridge = Bridge().get_agent_bridge()
            agent_id = self.request_to_agent.get(request_id)
            if not agent_id:
                try:
                    agent_id = agent_bridge.agent_router.resolve(
                        explicit_agent_id=json_data.get("agent_id"),
                    )
                except AgentUnavailableError:
                    # Session pinned to a since-deleted Agent; nothing in flight
                    # for it to cancel. Report success with a zero count rather
                    # than raising on every cancel attempt.
                    return json.dumps({"status": "success", "cancelled": 0})

            registry = get_cancel_registry()
            cancelled = 0

            if request_id:
                if registry.cancel_request(request_id):
                    cancelled = 1

            if cancelled == 0 and session_id:
                scoped_session_id = agent_bridge._cancel_key(
                    agent_id,
                    session_id,
                    agent_bridge.agent_registry.default_agent_id,
                )
                cancelled = registry.cancel_session(scoped_session_id)

            if request_id and request_id in self.sse_streams:
                self._publish_sse_event(request_id, {
                    "type": "cancelled",
                    "content": "🛑 Cancelled" if lang.startswith("en") else "🛑 已中止",
                    "request_id": request_id,
                    "timestamp": time.time(),
                })

            logger.info(
                f"[WebChannel] cancel request: request_id={request_id!r}, "
                f"session_id={session_id!r}, cancelled={cancelled}"
            )
            return json.dumps({
                "status": "success",
                "cancelled": cancelled,
            })

        except Exception as e:
            logger.error(f"[WebChannel] cancel_request error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def poll_response(self):
        """
        Poll for responses using the session_id.
        """
        try:
            data = web.data()
            json_data = json.loads(data)
            session_id = json_data.get('session_id')
            from bridge.bridge import Bridge
            from agent.routing import AgentUnavailableError
            agent_bridge = Bridge().get_agent_bridge()
            try:
                agent_id = agent_bridge.agent_router.resolve(
                    explicit_agent_id=json_data.get("agent_id"),
                )
            except AgentUnavailableError:
                # The session is pinned to an Agent that has since been deleted
                # or disabled (a stale client selection). Polling is read-only,
                # so there is nothing to answer - report no content instead of
                # raising every tick, which otherwise floods the log.
                return json.dumps({
                    "status": "success",
                    "has_content": False,
                    "agent_unavailable": True,
                })
            if not session_id:
                return json.dumps({"status": "error", "message": "Invalid session ID"})

            session_queue_key = self._session_queue_key(session_id, agent_id)

            # A polling client is declaring "I'm listening on this session", so
            # register a queue for it if one doesn't exist yet. Previously a
            # queue was only created when the user sent a message, which meant an
            # idle client (e.g. right after a restart, or a session opened but
            # not typed in) had nowhere for a scheduled/proactive push to land —
            # the push was dropped even though the client was actively polling.
            if session_queue_key not in self.session_queues:
                self.session_queues[session_queue_key] = Queue()

            # 尝试从队列获取响应，不等待
            try:
                # 使用peek而不是get，这样如果前端没有成功处理，下次还能获取到
                response = self.session_queues[session_queue_key].get(block=False)

                # 返回响应，包含请求ID以区分不同请求
                return json.dumps({
                    "status": "success",
                    "has_content": True,
                    "content": response["content"],
                    "request_id": response["request_id"],
                    "timestamp": response["timestamp"]
                })

            except Empty:
                # 没有新响应
                return json.dumps({"status": "success", "has_content": False})

        except Exception as e:
            logger.error(f"Error polling response: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def startup(self):
        configured_host = conf().get("web_host", "")
        host = configured_host or ("0.0.0.0" if _is_password_enabled() else "127.0.0.1")
        # The desktop app passes its chosen port via COW_WEB_PORT so its backend
        # never collides with a source-run web console (default 9899). This makes
        # the port a single source of truth owned by the Electron shell.
        port = int(os.environ.get("COW_WEB_PORT") or conf().get("web_port", 9899))
        is_public_bind = host in ("0.0.0.0", "::")

        self._cleanup_stale_voice_recordings()

        def _log_startup_banner():
            """Announce the console. Only called once the socket is actually
            bound — printing it up front made a failed bind look like a
            successful startup in the logs."""
            # Print available channel types (ordered by language: prioritize
            # locally-popular channels for the current UI language)
            logger.info(
                "[WebChannel] Available channels (edit `channel_type` in config.json to switch, separate multiple with commas):")
            zh_channels = [
                ("web", "Web"),
                ("terminal", "Terminal"),
                ("weixin", "WeChat"),
                ("feishu", "Feishu"),
                ("dingtalk", "DingTalk"),
                ("wecom_bot", "WeCom Bot"),
                ("wechatcom_app", "WeCom App"),
                ("wechat_kf", "WeChat Customer Service"),
                ("wechatmp", "WeChat Official Account"),
                ("wechatmp_service", "WeChat Official Account (Service)"),
                ("telegram", "Telegram"),
                ("slack", "Slack"),
                ("discord", "Discord"),
            ]
            en_channels = [
                ("web", "Web"),
                ("terminal", "Terminal"),
                ("telegram", "Telegram"),
                ("slack", "Slack"),
                ("discord", "Discord"),
                ("weixin", "WeChat"),
                ("feishu", "Feishu"),
                ("dingtalk", "DingTalk"),
                ("wecom_bot", "WeCom Bot"),
                ("wechatcom_app", "WeCom App"),
                ("wechat_kf", "WeChat Customer Service"),
                ("wechatmp", "WeChat Official Account"),
                ("wechatmp_service", "WeChat Official Account (Service)"),
            ]
            channels = en_channels if i18n.get_language() == "en" else zh_channels
            name_width = max(len(name) for name, _ in channels)
            for idx, (name, label) in enumerate(channels, 1):
                logger.info(f"[WebChannel]  {idx:>2}. {name:<{name_width}} - {label}")
            logger.info("[WebChannel] ✅ Web console is running")
            logger.info(f"[WebChannel] 🌐 Local access: http://localhost:{port}")
            if is_public_bind:
                logger.info(f"[WebChannel] 🌍 Server access: http://YOUR_IP:{port} (replace YOUR_IP with your server IP)")
                if not _is_password_enabled():
                    logger.info("[WebChannel] ⚠️  Listening on 0.0.0.0 without web_password set; set an access password in config.json for public deployment")
            else:
                logger.info(f"[WebChannel] 🔒 Listening on {host} only (local access). For public access, set web_host to 0.0.0.0 and configure web_password")

            # In desktop mode the Electron shell renders the UI, so don't pop a
            # browser window (also avoids issues when running detached/headless).
            if os.environ.get("COW_DESKTOP") != "1":
                try:
                    import webbrowser
                    webbrowser.open(f"http://localhost:{port}")
                    logger.debug(f"[WebChannel] Opened browser at http://localhost:{port}")
                except Exception as e:
                    logger.debug(f"[WebChannel] Could not open browser: {e}")

        # Ensure the static dir exists. In a packaged build it ships read-only
        # inside the bundle, so swallow errors instead of failing startup.
        web_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static_dir = os.path.join(web_dir, 'static')
        if not os.path.exists(static_dir):
            try:
                os.makedirs(static_dir)
                logger.debug(f"[WebChannel] Created static directory: {static_dir}")
            except OSError as e:
                logger.debug(f"[WebChannel] Skipped creating static dir (read-only bundle?): {e}")

        # Imported here rather than at module scope: web_channel.py imports
        # this module, and it is the one that owns the URL table, because
        # web.py resolves handler names out of the namespace they live in.
        # channel_factory only ever reaches this class through that module, so
        # it is already imported by the time startup() runs.
        from channel.web.web_channel import build_app
        app = build_app()

        # 完全禁用web.py的HTTP日志输出
        web.httpserver.LogMiddleware.log = lambda self, status, environ: None

        # 配置web.py的日志级别为ERROR
        logging.getLogger("web").setLevel(logging.ERROR)
        logging.getLogger("web.httpserver").setLevel(logging.ERROR)

        # Build WSGI app with middleware (same as runsimple but without print)
        func = web.httpserver.StaticMiddleware(app.wsgifunc())
        func = web.httpserver.LogMiddleware(func)
        server = web.httpserver.WSGIServer((host, port), func)
        server.daemon_threads = True
        # Default request_queue_size(5) / timeout(10s) / numthreads(10) are
        # too small: when SSE streams occupy many threads, the backlog fills
        # and new connections get refused (ERR_CONNECTION_ABORTED).
        server.request_queue_size = 128
        server.timeout = 300
        server.requests.min = 20
        server.requests.max = 80
        # Allow large attachments (screenshots, PDFs, short videos). cheroot's
        # default is unlimited (0), but pin an explicit, generous cap so an
        # oversized body fails with a clean 413 instead of a connection reset
        # that surfaces in the client as an opaque "Failed to fetch".
        try:
            server.max_request_body_size = 512 * 1024 * 1024  # 512 MB
        except Exception:
            pass
        self._http_server = server
        # Reclaim orphaned SSE logs so disconnected clients don't leak memory.
        self._start_sse_janitor()
        # prepare() binds the socket, serve() runs the accept loop. Splitting
        # start() into the two lets us report a bind failure with the port in
        # hand, and keeps the "console is running" banner honest: it now only
        # prints once we really own the port.
        try:
            server.prepare()
        except OSError as e:
            _log_bind_failure(host, port, e)
            raise
        SERVING.set()
        _log_startup_banner()
        try:
            server.serve()
        except (KeyboardInterrupt, SystemExit):
            server.stop()

    def stop(self):
        if self._http_server:
            try:
                self._http_server.stop()
                logger.info("[WebChannel] HTTP server stopped")
            except Exception as e:
                logger.warning(f"[WebChannel] Error stopping HTTP server: {e}")
            self._http_server = None
