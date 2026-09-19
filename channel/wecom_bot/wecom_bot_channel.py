"""
WeCom (企业微信) AI Bot channel via WebSocket long connection.

Supports:
- Single chat and group chat (text / image / file input & output)
- Scheduled task push via aibot_send_msg
- Heartbeat keep-alive and auto-reconnect
"""

import base64
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid

import requests
import web
import websocket

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.wecom_bot.wecom_bot_crypt import WecomBotCrypt
from channel.wecom_bot.wecom_bot_message import WecomBotMessage
from common import state_dir
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.ws_client_compat import websocket_app_run_forever
from config import conf

WECOM_WS_URL = "wss://openws.work.weixin.qq.com"
HEARTBEAT_INTERVAL = 30
MEDIA_CHUNK_SIZE = 512 * 1024  # 512KB per chunk (before base64 encoding)
# Fixed URL path for the callback (webhook) HTTP server. The bot's
# receive-message URL must point at this path, e.g. http://host:9892/wecombot
CALLBACK_PATH = "/wecombot"


def _media_tmp_path(prefix: str, ext: str = "") -> str:
    """Path for transient media this channel downloads or synthesizes.

    Transient media belongs in the agent's managed tmp dir -- the convention
    every other channel follows through ``common.state_dir.tmp_dir()``. A bare
    ``/tmp/...`` is not portable: on Windows it resolves against the *current
    drive*, so the same process writes to a different disk depending on where it
    was launched, and it sits outside the workspace the app manages (and cleans).
    ``tmp_dir()`` also creates the directory, which ``/tmp`` does not guarantee.
    """
    return os.path.join(str(state_dir.tmp_dir()), f"{prefix}_{uuid.uuid4().hex[:8]}{ext}")


def _escape_control_chars_inside_json_strings(s: str) -> str:
    """Escape U+0000–U+001F inside JSON string values so json.loads accepts WeCom payloads.

    The server occasionally emits raw newlines/tabs inside quoted fields, which is
    invalid strict JSON but recoverable without touching escapes like \\n or \\".
    """
    out = []
    in_string = False
    escape = False
    for c in s:
        if escape:
            out.append(c)
            escape = False
            continue
        if in_string and c == "\\":
            out.append(c)
            escape = True
            continue
        if c == '"':
            out.append(c)
            in_string = not in_string
            continue
        if in_string and ord(c) < 32:
            out.append("\\u%04x" % ord(c))
            continue
        out.append(c)
    return "".join(out)


def _loads_wecom_ws_json(raw):
    """Parse WebSocket JSON; tolerate unescaped control characters inside strings."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        raw = str(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        msg = str(e).lower()
        if "control character" in msg:
            return json.loads(_escape_control_chars_inside_json_strings(raw))
        raise


@singleton
class WecomBotChannel(ChatChannel):

    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.bot_id = ""
        self.bot_secret = ""
        self.received_msgs = ExpiredDict(60 * 60 * 7.1)
        self._ws = None
        self._ws_thread = None
        self._heartbeat_thread = None
        self._connected = False
        self._stop_event = threading.Event()
        self._pending_responses = {}  # req_id -> (threading.Event, result_holder)
        self._pending_lock = threading.Lock()
        self._stream_states = {}  # req_id -> {"stream_id": str, "content": str}

        # Transport mode: "websocket" (long connection) or "webhook" (HTTP callback)
        self.mode = "websocket"
        self._crypt = None
        self._http_server = None
        # stream_id -> {"committed", "current", "finished", "images", "last_access"}
        self._callback_streams = ExpiredDict(60 * 10)  # auto-expire after 10min (max poll window is 6min)
        self._callback_lock = threading.Lock()

        conf()["group_name_white_list"] = ["ALL_GROUP"]
        conf()["single_chat_prefix"] = [""]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self):
        self.mode = self.cfg("wecom_bot_mode", "websocket")
        # Webhook mode binds a fixed HTTP port, so it cannot host more than one
        # instance in a process. Only the websocket transport is multi-instance
        # ready; refuse to start a bound (multi-instance) webhook bot instead of
        # silently colliding on the port with another instance.
        if self.mode == "webhook":
            # Webhook binds a fixed HTTP port, so only one webhook bot can run
            # per process. The default (bootstrapped) instance keeps
            # instance_id == channel_type and is allowed — it is still the one
            # webhook bot, just carrying an Agent binding. An *extra* instance
            # (a distinct instance_id) would collide on the port, so refuse it
            # and point the user at websocket mode.
            iid = getattr(self, "instance_id", "") or ""
            if iid and iid != self.channel_type:
                err = (
                    "[WecomBot] webhook mode does not support multiple instances "
                    "(it binds a fixed port); use websocket mode for extra bots"
                )
                logger.error(err)
                self.report_startup_error(err)
                return
            self._startup_callback()
            return

        self.bot_id = self.cfg("wecom_bot_id", "")
        self.bot_secret = self.cfg("wecom_bot_secret", "")

        if not self.bot_id or not self.bot_secret:
            err = "[WecomBot] wecom_bot_id and wecom_bot_secret are required"
            logger.error(err)
            self.report_startup_error(err)
            return

        self._stop_event.clear()
        self._start_ws()

    def stop(self):
        logger.info("[WecomBot] stop() called")
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._connected = False
        if self._http_server:
            try:
                self._http_server.stop()
                logger.info("[WecomBot] Callback HTTP server stopped")
            except Exception as e:
                logger.warning(f"[WecomBot] Error stopping HTTP server: {e}")
            self._http_server = None

    # ------------------------------------------------------------------
    # WebSocket connection
    # ------------------------------------------------------------------

    def _start_ws(self):
        def _on_open(ws):
            logger.info("[WecomBot] WebSocket connected, sending subscribe...")
            self._send_subscribe()

        def _on_message(ws, raw):
            try:
                data = _loads_wecom_ws_json(raw)
                self._handle_ws_message(data)
            except Exception as e:
                logger.error(f"[WecomBot] Failed to handle ws message: {e}", exc_info=True)

        def _on_error(ws, error):
            logger.error(f"[WecomBot] WebSocket error: {error}")

        def _on_close(ws, close_status_code, close_msg):
            logger.warning(f"[WecomBot] WebSocket closed: status={close_status_code}, msg={close_msg}")
            self._connected = False
            if not self._stop_event.is_set():
                logger.info("[WecomBot] Will reconnect in 5s...")
                time.sleep(5)
                if not self._stop_event.is_set():
                    self._start_ws()

        self._ws = websocket.WebSocketApp(
            WECOM_WS_URL,
            on_open=_on_open,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )

        def run_forever():
            try:
                websocket_app_run_forever(self._ws, ping_interval=0, reconnect=0)
            except (SystemExit, KeyboardInterrupt):
                logger.info("[WecomBot] WebSocket thread interrupted")
            except Exception as e:
                logger.error(f"[WecomBot] WebSocket run_forever error: {e}")

        self._ws_thread = threading.Thread(target=run_forever, daemon=True)
        self._ws_thread.start()
        self._ws_thread.join()

    def _ws_send(self, data: dict):
        if self._ws:
            self._ws.send(json.dumps(data, ensure_ascii=False))

    def _gen_req_id(self) -> str:
        return uuid.uuid4().hex[:16]

    # ------------------------------------------------------------------
    # Callback (webhook) mode
    # ------------------------------------------------------------------

    def _startup_callback(self):
        """Start an HTTP server that receives encrypted callbacks (webhook mode).

        The bot's "接收消息" URL in the WeCom admin console should point at this
        server (any path is accepted). Verification (GET) and message delivery
        (POST) are both handled by ``WecomBotCallbackController``.
        """
        token = conf().get("wecom_bot_token", "")
        aes_key = conf().get("wecom_bot_encoding_aes_key", "")
        if not token or not aes_key:
            err = "[WecomBot] callback mode requires wecom_bot_token and wecom_bot_encoding_aes_key"
            logger.error(err)
            self.report_startup_error(err)
            return

        try:
            # Enterprise-internal smart bot: receive_id is an empty string.
            self._crypt = WecomBotCrypt(token, aes_key, "")
        except Exception as e:
            err = f"[WecomBot] invalid callback credentials: {e}"
            logger.error(err)
            self.report_startup_error(err)
            return

        port = int(conf().get("wecom_bot_port", 9892))
        logger.info(f"[WecomBot] Starting callback (webhook) server on port {port}, path {CALLBACK_PATH} ...")
        # Only serve the fixed callback path; everything else 404s instead of being
        # treated as a (signature-failing) WeCom callback.
        urls = (re.escape(CALLBACK_PATH), "channel.wecom_bot.wecom_bot_channel.WecomBotCallbackController")
        app = web.application(urls, globals(), autoreload=False)
        func = web.httpserver.StaticMiddleware(app.wsgifunc())
        func = web.httpserver.LogMiddleware(func)
        server = web.httpserver.WSGIServer(("0.0.0.0", port), func)
        self._http_server = server
        self.report_startup_success()
        try:
            server.start()
        except (KeyboardInterrupt, SystemExit):
            server.stop()

    def _new_callback_stream(self, response_url: str = "") -> str:
        """Create a new stream state and return its id."""
        stream_id = uuid.uuid4().hex[:16]
        now = time.time()
        with self._callback_lock:
            self._callback_streams[stream_id] = {
                "committed": "",
                "current": "",
                "finished": False,
                "images": [],  # list of (base64_str, md5_str), flushed only at finish
                "image_urls": [],  # public http(s) image urls (usable in response_url markdown)
                "image_pending": False,  # an image reply is being prepared; don't finish on text yet
                "last_access": now,
                "created_at": now,
                "response_url": response_url or "",
                "delivered": False,  # final answer handed to WeCom via a poll
                "url_sent": False,   # final answer pushed via response_url (active reply)
            }
        return stream_id

    def _callback_handle_message(self, data: dict) -> dict:
        """Handle a freshly-received user message in callback mode.

        Produces the context for async processing and returns the initial passive
        reply (a stream packet with finish=false) so WeCom starts polling for the
        agent's streamed answer. Returns ``None`` when there's nothing to reply
        (e.g. an image/file silently cached for the next query).
        """
        msg_id = data.get("msgid", "")
        if msg_id and self.received_msgs.get(msg_id):
            logger.debug(f"[WecomBot] Duplicate msg filtered: {msg_id}")
            return None
        if msg_id:
            self.received_msgs[msg_id] = True

        chattype = data.get("chattype", "single")
        is_group = chattype == "group"

        default_aeskey = conf().get("wecom_bot_encoding_aes_key", "")
        result = self._build_context(data, is_group, default_aeskey=default_aeskey)
        if not result:
            return None
        context, wecom_msg = result

        # response_url lets us actively reply once within 1h, used as a fallback
        # when the agent finishes after WeCom stops polling (max ~6min window).
        response_url = data.get("response_url", "") or ""
        stream_id = self._new_callback_stream(response_url=response_url)
        wecom_msg.stream_id = stream_id
        context["wecom_stream_id"] = stream_id
        context["on_event"] = self._make_callback_stream_callback(stream_id)
        self.produce(context)

        # First passive reply: register the stream id, WeCom will poll for updates.
        return {
            "msgtype": "stream",
            "stream": {"id": stream_id, "finish": False, "content": ""},
        }

    def _callback_handle_stream_poll(self, data: dict) -> dict:
        """Handle a "流式消息刷新" poll: return the latest accumulated content."""
        stream_id = data.get("stream", {}).get("id", "")
        with self._callback_lock:
            state = self._callback_streams.get(stream_id)
            if state is None:
                # Unknown / expired stream: tell WeCom we're done to stop polling.
                return {"msgtype": "stream", "stream": {"id": stream_id, "finish": True, "content": ""}}
            state["last_access"] = time.time()
            if state.get("url_sent"):
                # Final answer already pushed via response_url; finish silently.
                return {"msgtype": "stream", "stream": {"id": stream_id, "finish": True, "content": ""}}
            # We never force-finish on a timer: while a task is still running the
            # bubble should keep spinning until either the task finishes or the
            # user cancels. If WeCom's 6min window closes before completion, the
            # answer is delivered later via response_url instead.
            finished = state["finished"]
            content = state["committed"] + state["current"]
            images = state["images"] if finished else []
            if finished:
                state["delivered"] = True
                logger.debug(f"[WecomBot] stream {stream_id} delivered via poll, len={len(content)}, images={len(images)}")

        stream = {"id": stream_id, "finish": finished, "content": content}
        if images:
            stream["msg_item"] = [
                {"msgtype": "image", "image": {"base64": b64, "md5": md5}}
                for (b64, md5) in images
            ]
        return {"msgtype": "stream", "stream": stream}

    def _make_callback_stream_callback(self, stream_id: str):
        """Build an on_event callback that accumulates agent output into stream state.

        Mirrors the websocket streaming behaviour: intermediate turns (text before
        a tool call) are committed with a '---' separator; WeCom reads the full
        accumulated content on each poll.
        """
        def on_event(event: dict):
            event_type = event.get("type")
            edata = event.get("data", {})
            cancelled = False
            with self._callback_lock:
                state = self._callback_streams.get(stream_id)
                if not state:
                    return

                if event_type == "turn_start":
                    state["current"] = ""
                elif event_type == "message_update":
                    delta = edata.get("delta", "")
                    if delta:
                        state["current"] += delta
                elif event_type == "message_end":
                    tool_calls = edata.get("tool_calls", [])
                    if tool_calls:
                        if state["current"].strip():
                            state["committed"] += state["current"].strip() + "\n\n---\n\n"
                            state["current"] = ""
                    else:
                        state["committed"] += state["current"]
                        state["current"] = ""
                elif event_type == "agent_cancelled":
                    # Mechanism 1: a cancelled run never reaches send(), so finalize
                    # its stream here to stop the "···" bubble immediately.
                    if state["current"]:
                        state["committed"] += state["current"]
                        state["current"] = ""
                    state["committed"] = state["committed"].rstrip()
                    if state["committed"].endswith("---"):
                        state["committed"] = state["committed"][:-3].rstrip()
                    if not state["committed"].strip():
                        state["committed"] = "🛑 已中止"
                    state["finished"] = True
                    state["last_access"] = time.time()
                    cancelled = True

            if cancelled:
                # Outside the lock: response_url fallback re-acquires it.
                self._schedule_response_url_fallback(stream_id)

        return on_event

    # ------------------------------------------------------------------
    # Subscribe & heartbeat
    # ------------------------------------------------------------------

    def _send_subscribe(self):
        self._ws_send({
            "cmd": "aibot_subscribe",
            "headers": {"req_id": self._gen_req_id()},
            "body": {
                "bot_id": self.bot_id,
                "secret": self.bot_secret,
            },
        })

    def _start_heartbeat(self):
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def heartbeat_loop():
            while not self._stop_event.is_set() and self._connected:
                try:
                    self._ws_send({
                        "cmd": "ping",
                        "headers": {"req_id": self._gen_req_id()},
                    })
                except Exception as e:
                    logger.warning(f"[WecomBot] Heartbeat send failed: {e}")
                    break
                self._stop_event.wait(HEARTBEAT_INTERVAL)

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    # ------------------------------------------------------------------
    # Incoming message dispatch
    # ------------------------------------------------------------------

    def _send_and_wait(self, data: dict, timeout: float = 15) -> dict:
        """Send a ws message and wait for the matching response by req_id."""
        req_id = data.get("headers", {}).get("req_id", "")
        event = threading.Event()
        holder = {"data": None}
        with self._pending_lock:
            self._pending_responses[req_id] = (event, holder)
        self._ws_send(data)
        event.wait(timeout=timeout)
        with self._pending_lock:
            self._pending_responses.pop(req_id, None)
        return holder["data"] or {}

    def _handle_ws_message(self, data: dict):
        cmd = data.get("cmd", "")
        errcode = data.get("errcode")
        req_id = data.get("headers", {}).get("req_id", "")

        # Check if this is a response to a pending request
        if req_id:
            with self._pending_lock:
                pending = self._pending_responses.get(req_id)
            if pending:
                event, holder = pending
                holder["data"] = data
                event.set()
                return

        # Subscribe response (only handle once before connected)
        if errcode is not None and cmd == "":
            if not self._connected:
                if errcode == 0:
                    logger.info("[WecomBot] ✅ Subscribe success")
                    self._connected = True
                    self._start_heartbeat()
                    self.report_startup_success()
                else:
                    errmsg = data.get("errmsg", "unknown error")
                    logger.error(f"[WecomBot] Subscribe failed: errcode={errcode}, errmsg={errmsg}")
                    self.report_startup_error(errmsg)
            return

        if cmd == "aibot_msg_callback":
            self._handle_msg_callback(data)
        elif cmd == "aibot_event_callback":
            self._handle_event_callback(data)
        elif cmd == "":
            if errcode and errcode != 0:
                logger.warning(f"[WecomBot] Response error: {data}")

    # ------------------------------------------------------------------
    # Message callback
    # ------------------------------------------------------------------

    def _handle_msg_callback(self, data: dict):
        body = data.get("body", {})
        req_id = data.get("headers", {}).get("req_id", "")
        msg_id = body.get("msgid", "")

        if self.received_msgs.get(msg_id):
            logger.debug(f"[WecomBot] Duplicate msg filtered: {msg_id}")
            return
        self.received_msgs[msg_id] = True

        chattype = body.get("chattype", "single")
        is_group = chattype == "group"

        result = self._build_context(body, is_group)
        if not result:
            return
        context, wecom_msg = result
        wecom_msg.req_id = req_id
        if req_id:
            context["on_event"] = self._make_stream_callback(req_id)
        from agent.team_addressing import stamp_speaker_from_channel
        stamp_speaker_from_channel(self, context, wecom_msg.content)
        self.produce(context)

    def _build_context(self, body: dict, is_group: bool, default_aeskey: str = ""):
        """Parse a wecom message body into a Context, applying file-cache logic.

        Shared by both the websocket (long-connection) and callback (webhook)
        receive paths. Returns ``(context, wecom_msg)`` when the message should be
        handed to the agent, or ``None`` when it was consumed (cached image/file,
        parse failure, etc.).
        """
        try:
            wecom_msg = WecomBotMessage(body, is_group=is_group, default_aeskey=default_aeskey)
        except NotImplementedError as e:
            logger.warning(f"[WecomBot] {e}")
            return None
        except Exception as e:
            logger.error(f"[WecomBot] Failed to parse message: {e}", exc_info=True)
            return None

        # File cache logic (same pattern as feishu)
        from channel.file_cache import get_file_cache
        file_cache = get_file_cache()

        if is_group:
            if conf().get("group_shared_session", True):
                session_id = body.get("chatid", "")
            else:
                session_id = wecom_msg.from_user_id + "_" + body.get("chatid", "")
        else:
            session_id = wecom_msg.from_user_id

        if wecom_msg.ctype == ContextType.IMAGE:
            if hasattr(wecom_msg, "image_path") and wecom_msg.image_path:
                file_cache.add(session_id, wecom_msg.image_path, file_type="image")
                logger.info(f"[WecomBot] Image cached for session {session_id}")
            return None

        if wecom_msg.ctype == ContextType.FILE:
            wecom_msg.prepare()
            file_cache.add(session_id, wecom_msg.content, file_type="file")
            logger.info(f"[WecomBot] File cached for session {session_id}: {wecom_msg.content}")
            return None

        if wecom_msg.ctype == ContextType.TEXT:
            cached_files = file_cache.get(session_id)
            if cached_files:
                file_refs = []
                for fi in cached_files:
                    ftype = fi["type"]
                    fpath = fi["path"]
                    if ftype == "image":
                        file_refs.append(f"[图片: {fpath}]")
                    elif ftype == "video":
                        file_refs.append(f"[视频: {fpath}]")
                    else:
                        file_refs.append(f"[文件: {fpath}]")
                wecom_msg.content = wecom_msg.content + "\n" + "\n".join(file_refs)
                logger.info(f"[WecomBot] Attached {len(cached_files)} cached file(s)")
                file_cache.clear(session_id)

        context = self._compose_context(
            wecom_msg.ctype,
            wecom_msg.content,
            isgroup=is_group,
            msg=wecom_msg,
            no_need_at=True,
        )
        if not context:
            return None
        return context, wecom_msg

    # ------------------------------------------------------------------
    # Event callback
    # ------------------------------------------------------------------

    def _handle_event_callback(self, data: dict):
        body = data.get("body", {})
        event = body.get("event", {})
        event_type = event.get("eventtype", "")

        if event_type == "enter_chat":
            logger.info(f"[WecomBot] User entered chat: {body.get('from', {}).get('userid')}")
        elif event_type == "disconnected_event":
            logger.warning("[WecomBot] Received disconnected_event, another connection took over")
        else:
            logger.debug(f"[WecomBot] Event: {event_type}")

    # ------------------------------------------------------------------
    # Stream callback (for agent on_event)
    # ------------------------------------------------------------------

    def _make_stream_callback(self, req_id: str):
        """Build an on_event callback that pushes agent stream deltas to wecom via stream message.

        All intermediate segments (thinking before tool calls) and the final answer
        are accumulated into a single stream message, separated by '---'.
        Throttles push to at most once per 100ms to avoid WebSocket congestion.
        """
        stream_id = uuid.uuid4().hex[:16]
        self._stream_states[req_id] = {
            "stream_id": stream_id,
            "committed": "",
            "current": "",
            "last_push_time": 0,
            "last_push_len": 0,
        }

        def _push_stream(state: dict, force: bool = False):
            """Push current stream content to wecom (throttled unless forced)."""
            now = time.time()
            if not force and now - state["last_push_time"] < 0.1:
                return
            content = state["committed"] + state["current"]
            if len(content) == state["last_push_len"]:
                return
            state["last_push_time"] = now
            state["last_push_len"] = len(content)
            try:
                self._ws_send({
                    "cmd": "aibot_respond_msg",
                    "headers": {"req_id": req_id},
                    "body": {
                        "msgtype": "stream",
                        "stream": {
                            "id": state["stream_id"],
                            "finish": False,
                            "content": content,
                        },
                    },
                })
            except Exception as e:
                logger.warning(f"[WecomBot] Stream push failed: {e}")

        def on_event(event: dict):
            event_type = event.get("type")
            data = event.get("data", {})
            state = self._stream_states.get(req_id)
            if not state:
                return

            if event_type == "turn_start":
                state["current"] = ""

            elif event_type == "message_update":
                delta = data.get("delta", "")
                if delta:
                    state["current"] += delta
                    _push_stream(state)

            elif event_type == "message_end":
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    if state["current"].strip():
                        state["committed"] += state["current"].strip() + "\n\n---\n\n"
                        state["current"] = ""
                else:
                    state["committed"] += state["current"]
                    state["current"] = ""
                _push_stream(state, force=True)

            elif event_type == "agent_cancelled":
                # Flush partial output and strip trailing "---" separator
                # left over from previous turn, to avoid a dangling divider.
                if state["current"]:
                    state["committed"] += state["current"]
                    state["current"] = ""
                state["committed"] = state["committed"].rstrip()
                if state["committed"].endswith("---"):
                    state["committed"] = state["committed"][:-3].rstrip()
                _push_stream(state, force=True)

        return on_event

    # ------------------------------------------------------------------
    # _compose_context (same pattern as feishu)
    # ------------------------------------------------------------------

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        context = Context(ctype, content)
        context.kwargs = kwargs
        if "channel_type" not in context:
            context["channel_type"] = self.channel_type
        self.stamp_instance_context(context)
        if "origin_ctype" not in context:
            context["origin_ctype"] = ctype

        cmsg = context["msg"]

        if cmsg.is_group:
            if conf().get("group_shared_session", True):
                context["session_id"] = cmsg.other_user_id
            else:
                context["session_id"] = f"{cmsg.from_user_id}:{cmsg.other_user_id}"
        else:
            context["session_id"] = cmsg.from_user_id

        context["receiver"] = cmsg.other_user_id

        if ctype == ContextType.TEXT:
            img_match_prefix = check_prefix(content, conf().get("image_create_prefix"))
            if img_match_prefix:
                content = content.replace(img_match_prefix, "", 1)
                context.type = ContextType.IMAGE_CREATE
            else:
                context.type = ContextType.TEXT
            context.content = content.strip()
            if "desire_rtype" not in context and conf().get("always_reply_voice"):
                context["desire_rtype"] = ReplyType.VOICE

        return context

    # ------------------------------------------------------------------
    # Callback (webhook) send: write the final reply into the stream state
    # so the next "流式消息刷新" poll returns it with finish=true.
    # ------------------------------------------------------------------

    def _callback_send(self, reply: Reply, context: Context):
        msg = context.get("msg")
        stream_id = getattr(msg, "stream_id", None) if msg else None
        if not stream_id:
            stream_id = context.get("wecom_stream_id")
        if not stream_id:
            logger.warning("[WecomBot] callback send without stream_id, dropping reply")
            return

        if reply.type == ReplyType.TEXT:
            self._callback_finalize_text(stream_id, reply.content)
        elif reply.type in (ReplyType.IMAGE_URL, ReplyType.IMAGE):
            self._callback_finalize_image(stream_id, reply.content)
        elif reply.type == ReplyType.FILE:
            # Passive callback replies only support text + image (base64); files
            # are not supported by the protocol, so append a notice to whatever
            # text the agent already streamed (do not drop it).
            text = getattr(reply, "text_content", "") or ""
            note = (text + "\n\n" if text else "") + "（文件无法在企微回调模式下直接发送）"
            self._callback_finalize_text(stream_id, note, append=True)
        elif reply.type in (ReplyType.VIDEO, ReplyType.VIDEO_URL, ReplyType.VOICE):
            logger.warning(f"[WecomBot] reply type {reply.type} not supported in callback mode")
            text = getattr(reply, "text_content", "") or ""
            note = (text + "\n\n" if text else "") + "（该消息类型无法在企微回调模式下直接发送）"
            self._callback_finalize_text(stream_id, note, append=True)
        else:
            self._callback_finalize_text(stream_id, str(reply.content))

    def _callback_get_or_create_state(self, stream_id: str) -> dict:
        state = self._callback_streams.get(stream_id)
        if state is None:
            now = time.time()
            state = {
                "committed": "",
                "current": "",
                "finished": False,
                "images": [],
                "image_urls": [],
                "image_pending": False,
                "last_access": now,
                "created_at": now,
                "response_url": "",
                "delivered": False,
                "url_sent": False,
            }
            self._callback_streams[stream_id] = state
        return state

    def _callback_finalize_text(self, stream_id: str, content: str, append: bool = False):
        with self._callback_lock:
            state = self._callback_get_or_create_state(stream_id)
            accumulated = (state["committed"] + state["current"]).strip()
            if append and accumulated:
                state["committed"] = (accumulated + "\n\n" + (content or "")).strip()
            else:
                state["committed"] = accumulated if accumulated else (content or "")
            state["current"] = ""
            state["last_access"] = time.time()
        # Don't finish synchronously: chat_channel splits an image-with-caption
        # reply into a TEXT send followed (0.3s later) by the IMAGE send. If the
        # text finished the stream immediately, WeCom would close it before the
        # image arrives. Defer the finish so a trailing image can merge in.
        self._schedule_text_finish(stream_id)

    def _schedule_text_finish(self, stream_id: str, delay: float = 1.2):
        def _run():
            time.sleep(delay)
            with self._callback_lock:
                state = self._callback_streams.get(stream_id)
                if not state or state["finished"] or state.get("image_pending"):
                    return  # already finished, or an image reply is on its way
                state["finished"] = True
                state["last_access"] = time.time()
            self._schedule_response_url_fallback(stream_id)

        threading.Thread(target=_run, daemon=True, name=f"wecom-textfin-{stream_id}").start()

    def _callback_finalize_image(self, stream_id: str, img_path_or_url: str):
        # Mark the image as pending up front (before the slow load/compress) so a
        # preceding text finalize won't close the stream while we work.
        with self._callback_lock:
            self._callback_get_or_create_state(stream_id)["image_pending"] = True
        b64md5 = self._load_image_base64(img_path_or_url)
        with self._callback_lock:
            state = self._callback_get_or_create_state(stream_id)
            accumulated = (state["committed"] + state["current"]).strip()
            state["current"] = ""
            if b64md5:
                state["images"].append(b64md5)
                state["committed"] = accumulated
                # Remember the public url (if any) so the response_url fallback
                # can embed it as markdown when the poll window has closed.
                if img_path_or_url.startswith(("http://", "https://")):
                    state["image_urls"].append(img_path_or_url)
            else:
                state["committed"] = accumulated or "[图片发送失败]"
            state["finished"] = True
            state["image_pending"] = False
            state["last_access"] = time.time()
        self._schedule_response_url_fallback(stream_id)

    # ------------------------------------------------------------------
    # Active reply fallback (response_url): rescue replies that finish after
    # WeCom stops polling (the passive stream window is ~6 min from the user's
    # message). A short delay lets an in-flight poll deliver first; only if no
    # poll picks up the finished answer do we push it actively via response_url.
    # ------------------------------------------------------------------

    def _schedule_response_url_fallback(self, stream_id: str, delay: float = 3.0):
        def _run():
            time.sleep(delay)
            with self._callback_lock:
                state = self._callback_streams.get(stream_id)
                if not state:
                    return
                if state.get("delivered") or state.get("url_sent"):
                    return  # a poll already delivered (or fallback already ran)
                response_url = state.get("response_url") or ""
                if not response_url:
                    logger.warning(
                        f"[WecomBot] stream {stream_id} finished after poll window but no response_url; reply dropped"
                    )
                    return
                content = (state["committed"] + state["current"]).strip()
                image_urls = list(state.get("image_urls") or [])
                has_images = bool(state.get("images"))
                state["url_sent"] = True

            self._send_via_response_url(stream_id, response_url, content, image_urls, has_images)

        threading.Thread(target=_run, daemon=True, name=f"wecom-respurl-{stream_id}").start()

    def _send_via_response_url(self, stream_id, response_url, content, image_urls, has_images):
        """Push a one-shot active markdown reply to response_url (valid 1h, single use)."""
        md = content or ""
        if image_urls:
            md += ("\n\n" if md else "") + "\n".join(f"![]({u})" for u in image_urls)
        elif has_images:
            md += ("\n\n" if md else "") + "（图片已生成，但因处理超时无法通过回调发送）"
        if not md:
            md = "（处理完成）"
        payload = {"msgtype": "markdown", "markdown": {"content": md}}
        try:
            resp = requests.post(response_url, json=payload, timeout=15)
            logger.info(
                f"[WecomBot] response_url active reply sent for {stream_id}: "
                f"status={resp.status_code}, body={resp.text[:200]}"
            )
        except Exception as e:
            logger.error(f"[WecomBot] response_url active reply failed for {stream_id}: {e}")

    def _load_image_base64(self, img_path_or_url: str):
        """Load a local/remote image, ensure JPG/PNG within 10MB, return (base64, md5)."""
        local_path = img_path_or_url
        if local_path.startswith("file://"):
            local_path = local_path[7:]

        # Temp files we create here (downloads/conversions/compressions) must be
        # cleaned up afterwards; the caller's original local file must not be.
        temp_files = []
        try:
            if local_path.startswith(("http://", "https://")):
                try:
                    resp = requests.get(local_path, timeout=30)
                    resp.raise_for_status()
                    tmp_path = _media_tmp_path("wecom_cb_img")
                    with open(tmp_path, "wb") as f:
                        f.write(resp.content)
                    temp_files.append(tmp_path)
                    local_path = tmp_path
                except Exception as e:
                    logger.error(f"[WecomBot] Failed to download image for callback reply: {e}")
                    return None

            if not os.path.exists(local_path):
                logger.error(f"[WecomBot] Image file not found: {local_path}")
                return None

            formatted = self._ensure_image_format(local_path)
            if not formatted:
                return None
            if formatted != local_path:
                temp_files.append(formatted)
            local_path = formatted

            # Unlike the long-connection path (which uploads and sends only a tiny
            # media_id), the callback reply embeds the whole image as base64 inside
            # an AES-encrypted body that is returned on EVERY poll. Empirically a
            # ~1.5MB image (base64 ~2.1MB, encrypted ~2.8MB) makes WeCom reject the
            # finish packet and poll forever, so cap well below that.
            callback_max_size = 512 * 1024
            if os.path.getsize(local_path) > callback_max_size:
                compressed = self._compress_image(local_path, callback_max_size)
                if compressed:
                    temp_files.append(compressed)
                    local_path = compressed
                else:
                    logger.warning("[WecomBot] callback image compress failed; sending original (may be rejected)")

            try:
                with open(local_path, "rb") as f:
                    raw = f.read()
                return base64.b64encode(raw).decode("utf-8"), hashlib.md5(raw).hexdigest()
            except Exception as e:
                logger.error(f"[WecomBot] Failed to read image for callback reply: {e}")
                return None
        finally:
            for path in temp_files:
                try:
                    os.remove(path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Send reply
    # ------------------------------------------------------------------

    def send(self, reply: Reply, context: Context):
        if self.mode == "webhook":
            self._callback_send(reply, context)
            return

        msg = context.get("msg")
        is_group = context.get("isgroup", False)
        receiver = context.get("receiver", "")

        # Determine req_id for responding or use send_msg for scheduled push
        req_id = getattr(msg, "req_id", None) if msg else None

        if reply.type == ReplyType.TEXT:
            self._send_text(reply.content, receiver, is_group, req_id)
        elif reply.type in (ReplyType.IMAGE_URL, ReplyType.IMAGE):
            self._send_image(reply.content, receiver, is_group, req_id)
        elif reply.type == ReplyType.FILE:
            if hasattr(reply, "text_content") and reply.text_content:
                self._send_text(reply.text_content, receiver, is_group, req_id)
                time.sleep(0.3)
            self._send_file(reply.content, receiver, is_group, req_id)
        elif reply.type == ReplyType.VIDEO or reply.type == ReplyType.VIDEO_URL:
            self._send_file(reply.content, receiver, is_group, req_id, media_type="video")
        elif reply.type == ReplyType.VOICE:
            self._send_voice(reply.content, receiver, is_group, req_id)
        else:
            logger.warning(f"[WecomBot] Unsupported reply type: {reply.type}, falling back to text")
            self._send_text(str(reply.content), receiver, is_group, req_id)

    # ------------------------------------------------------------------
    # Respond message (via websocket)
    # ------------------------------------------------------------------

    def _send_text(self, content: str, receiver: str, is_group: bool, req_id: str = None):
        """Send text/markdown reply. Reuses stream state if available (streaming mode)."""
        if req_id:
            state = self._stream_states.pop(req_id, None)
            if state:
                final_content = state["committed"] if state["committed"] else content
                stream_id = state["stream_id"]
            else:
                final_content = content
                stream_id = uuid.uuid4().hex[:16]

            # Brief pause so the server finishes processing the last intermediate chunk
            # before receiving the finish packet
            time.sleep(0.15)

            self._ws_send({
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id},
                "body": {
                    "msgtype": "stream",
                    "stream": {
                        "id": stream_id,
                        "finish": True,
                        "content": final_content,
                    },
                },
            })
        else:
            self._active_send_markdown(content, receiver, is_group)

    def _send_image(self, img_path_or_url: str, receiver: str, is_group: bool, req_id: str = None):
        """Send image reply. Converts to JPG/PNG and compresses if >2MB."""
        local_path = img_path_or_url
        if local_path.startswith("file://"):
            local_path = local_path[7:]

        if local_path.startswith(("http://", "https://")):
            try:
                resp = requests.get(local_path, timeout=30)
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "")
                if "jpeg" in ct or "jpg" in ct:
                    ext = ".jpg"
                elif "webp" in ct:
                    ext = ".webp"
                elif "gif" in ct:
                    ext = ".gif"
                else:
                    ext = ".png"
                tmp_path = _media_tmp_path("wecom_img", ext)
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"[WecomBot] Image downloaded: size={len(resp.content)}, "
                            f"content-type={ct}, path={tmp_path}")
                local_path = tmp_path
            except Exception as e:
                logger.error(f"[WecomBot] Failed to download image for sending: {e}")
                self._send_text("[Image send failed]", receiver, is_group, req_id)
                return

        if not os.path.exists(local_path):
            logger.error(f"[WecomBot] Image file not found: {local_path}")
            return

        max_image_size = 2 * 1024 * 1024  # 2MB limit for image upload
        local_path = self._ensure_image_format(local_path)
        if not local_path:
            self._send_text("[Image format conversion failed]", receiver, is_group, req_id)
            return

        if os.path.getsize(local_path) > max_image_size:
            local_path = self._compress_image(local_path, max_image_size)
            if not local_path:
                self._send_text("[Image too large]", receiver, is_group, req_id)
                return

        file_size = os.path.getsize(local_path)
        logger.info(f"[WecomBot] Uploading image: path={local_path}, size={file_size} bytes")
        media_id = self._upload_media(local_path, "image")
        if not media_id:
            logger.error("[WecomBot] Failed to upload image")
            self._send_text("[Image upload failed]", receiver, is_group, req_id)
            return

        if req_id:
            self._ws_send({
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id},
                "body": {
                    "msgtype": "image",
                    "image": {"media_id": media_id},
                },
            })
        else:
            self._ws_send({
                "cmd": "aibot_send_msg",
                "headers": {"req_id": self._gen_req_id()},
                "body": {
                    "chatid": receiver,
                    "chat_type": 2 if is_group else 1,
                    "msgtype": "image",
                    "image": {"media_id": media_id},
                },
            })

    @staticmethod
    def _ensure_image_format(file_path: str) -> str:
        """Ensure image is JPG or PNG (the only formats wecom supports). Convert if needed."""
        try:
            from PIL import Image
            img = Image.open(file_path)
            fmt = (img.format or "").upper()
            if fmt in ("JPEG", "PNG"):
                # Already a supported format, but make sure the filename extension matches
                ext = os.path.splitext(file_path)[1].lower()
                if fmt == "JPEG" and ext in (".jpg", ".jpeg"):
                    return file_path
                if fmt == "PNG" and ext == ".png":
                    return file_path
                # Extension doesn't match — rename/copy with correct extension
                correct_ext = ".jpg" if fmt == "JPEG" else ".png"
                out_path = _media_tmp_path("wecom_fmt", correct_ext)
                img.save(out_path, fmt)
                logger.info(f"[WecomBot] Image renamed: {file_path} -> {out_path} ({fmt})")
                return out_path

            # Unsupported format (WebP, GIF, BMP, etc.) — convert to PNG
            if img.mode == "RGBA":
                out_path = _media_tmp_path("wecom_fmt", ".png")
                img.save(out_path, "PNG")
            else:
                out_path = _media_tmp_path("wecom_fmt", ".jpg")
                img.convert("RGB").save(out_path, "JPEG", quality=90)
            logger.info(f"[WecomBot] Image converted from {fmt} -> {out_path}")
            return out_path
        except Exception as e:
            logger.error(f"[WecomBot] Image format check failed: {e}")
            return file_path

    @staticmethod
    def _compress_image(file_path: str, max_bytes: int) -> str:
        """Compress image to fit within max_bytes. Returns new path or empty string."""
        try:
            from PIL import Image
            img = Image.open(file_path)
            if img.mode == "RGBA":
                img = img.convert("RGB")

            out_path = _media_tmp_path("wecom_compressed", ".jpg")
            quality = 85
            while quality >= 30:
                img.save(out_path, "JPEG", quality=quality, optimize=True)
                if os.path.getsize(out_path) <= max_bytes:
                    logger.info(f"[WecomBot] Image compressed: quality={quality}, "
                                f"size={os.path.getsize(out_path)} bytes")
                    return out_path
                quality -= 10

            # Still too large — resize
            ratio = (max_bytes / os.path.getsize(out_path)) ** 0.5
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            img.save(out_path, "JPEG", quality=70, optimize=True)
            if os.path.getsize(out_path) <= max_bytes:
                logger.info(f"[WecomBot] Image compressed with resize: {new_size}, "
                            f"size={os.path.getsize(out_path)} bytes")
                return out_path

            logger.error(f"[WecomBot] Cannot compress image below {max_bytes} bytes")
            return ""
        except Exception as e:
            logger.error(f"[WecomBot] Image compression failed: {e}")
            return ""

    def _send_file(self, file_path: str, receiver: str, is_group: bool,
                   req_id: str = None, media_type: str = "file"):
        """Send file/video reply by uploading media first."""
        local_path = file_path
        if local_path.startswith("file://"):
            local_path = local_path[7:]

        if local_path.startswith(("http://", "https://")):
            try:
                resp = requests.get(local_path, timeout=60)
                resp.raise_for_status()
                ext = os.path.splitext(local_path)[1] or ".bin"
                tmp_path = _media_tmp_path("wecom_file", ext)
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
                local_path = tmp_path
            except Exception as e:
                logger.error(f"[WecomBot] Failed to download file for sending: {e}")
                return

        if not os.path.exists(local_path):
            logger.error(f"[WecomBot] File not found: {local_path}")
            return

        media_id = self._upload_media(local_path, media_type)
        if not media_id:
            logger.error(f"[WecomBot] Failed to upload {media_type}")
            return

        if req_id:
            self._ws_send({
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id},
                "body": {
                    "msgtype": media_type,
                    media_type: {"media_id": media_id},
                },
            })
        else:
            self._ws_send({
                "cmd": "aibot_send_msg",
                "headers": {"req_id": self._gen_req_id()},
                "body": {
                    "chatid": receiver,
                    "chat_type": 2 if is_group else 1,
                    "msgtype": media_type,
                    media_type: {"media_id": media_id},
                },
            })

    def _send_voice(self, voice_path: str, receiver: str, is_group: bool, req_id: str = None):
        """Send native voice reply. WeCom voice media must be amr."""
        local_path = voice_path
        if local_path.startswith("file://"):
            local_path = local_path[7:]

        if local_path.startswith(("http://", "https://")):
            try:
                resp = requests.get(local_path, timeout=60)
                resp.raise_for_status()
                ext = os.path.splitext(local_path)[1] or ".mp3"
                tmp_path = _media_tmp_path("wecom_voice", ext)
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
                local_path = tmp_path
            except Exception as e:
                logger.error(f"[WecomBot] Failed to download voice for sending: {e}")
                return

        if not os.path.exists(local_path):
            logger.error(f"[WecomBot] Voice file not found: {local_path}")
            return

        amr_path = local_path
        if not local_path.lower().endswith(".amr"):
            try:
                from voice.audio_convert import any_to_amr
                amr_path = os.path.splitext(local_path)[0] + ".amr"
                any_to_amr(local_path, amr_path)
            except Exception as e:
                logger.error(f"[WecomBot] Failed to convert voice to amr: {e}")
                return

        media_id = self._upload_media(amr_path, "voice")
        if not media_id:
            logger.error("[WecomBot] Failed to upload voice media")
            return

        if req_id:
            self._ws_send({
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id},
                "body": {
                    "msgtype": "voice",
                    "voice": {"media_id": media_id},
                },
            })
        else:
            self._ws_send({
                "cmd": "aibot_send_msg",
                "headers": {"req_id": self._gen_req_id()},
                "body": {
                    "chatid": receiver,
                    "chat_type": 2 if is_group else 1,
                    "msgtype": "voice",
                    "voice": {"media_id": media_id},
                },
            })

    def _active_send_markdown(self, content: str, receiver: str, is_group: bool):
        """Proactively send markdown message (for scheduled tasks, no req_id)."""
        self._ws_send({
            "cmd": "aibot_send_msg",
            "headers": {"req_id": self._gen_req_id()},
            "body": {
                "chatid": receiver,
                "chat_type": 2 if is_group else 1,
                "msgtype": "markdown",
                "markdown": {"content": content},
            },
        })

    # ------------------------------------------------------------------
    # Media upload (chunked)
    # ------------------------------------------------------------------

    def _upload_media(self, file_path: str, media_type: str = "file") -> str:
        """
        Upload a local file to wecom bot via chunked upload protocol.
        Returns media_id on success, empty string on failure.
        """
        if not os.path.exists(file_path):
            logger.error(f"[WecomBot] Upload file not found: {file_path}")
            return ""

        file_size = os.path.getsize(file_path)
        if file_size < 5:
            logger.error(f"[WecomBot] File too small: {file_size} bytes")
            return ""

        filename = os.path.basename(file_path)
        total_chunks = math.ceil(file_size / MEDIA_CHUNK_SIZE)
        if total_chunks > 100:
            logger.error(f"[WecomBot] Too many chunks: {total_chunks} > 100")
            return ""

        file_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                file_md5.update(block)
        md5_hex = file_md5.hexdigest()

        # 1. Init upload
        init_resp = self._send_and_wait({
            "cmd": "aibot_upload_media_init",
            "headers": {"req_id": self._gen_req_id()},
            "body": {
                "type": media_type,
                "filename": filename,
                "total_size": file_size,
                "total_chunks": total_chunks,
                "md5": md5_hex,
            },
        }, timeout=15)

        if init_resp.get("errcode") != 0:
            logger.error(f"[WecomBot] Upload init failed: {init_resp}")
            return ""

        upload_id = init_resp.get("body", {}).get("upload_id")
        if not upload_id:
            logger.error("[WecomBot] Failed to get upload_id")
            return ""

        # 2. Upload chunks
        with open(file_path, "rb") as f:
            for idx in range(total_chunks):
                chunk = f.read(MEDIA_CHUNK_SIZE)
                b64_data = base64.b64encode(chunk).decode("utf-8")
                chunk_resp = self._send_and_wait({
                    "cmd": "aibot_upload_media_chunk",
                    "headers": {"req_id": self._gen_req_id()},
                    "body": {
                        "upload_id": upload_id,
                        "chunk_index": idx,
                        "base64_data": b64_data,
                    },
                }, timeout=30)
                if chunk_resp.get("errcode") != 0:
                    logger.error(f"[WecomBot] Chunk {idx} upload failed: {chunk_resp}")
                    return ""

        # 3. Finish upload
        finish_resp = self._send_and_wait({
            "cmd": "aibot_upload_media_finish",
            "headers": {"req_id": self._gen_req_id()},
            "body": {"upload_id": upload_id},
        }, timeout=30)

        if finish_resp.get("errcode") != 0:
            logger.error(f"[WecomBot] Upload finish failed: {finish_resp}")
            return ""

        media_id = finish_resp.get("body", {}).get("media_id", "")
        if media_id:
            logger.info(f"[WecomBot] Media uploaded: media_id={media_id}")
        else:
            logger.error("[WecomBot] Failed to get media_id from finish response")
        return media_id


class WecomBotCallbackController:
    """HTTP controller for wecom bot callback (webhook) mode.

    - GET  : URL verification (echo the decrypted echostr).
    - POST : encrypted message / stream-refresh / event callbacks; returns an
             encrypted passive reply (or "success" for an empty reply).
    """

    @staticmethod
    def _channel() -> "WecomBotChannel":
        return WecomBotChannel()

    def GET(self):
        channel = self._channel()
        params = web.input(msg_signature="", timestamp="", nonce="", echostr="")
        if not channel._crypt:
            return "wecom bot callback not ready"
        ret, echo = channel._crypt.verify_url(
            params.msg_signature, params.timestamp, params.nonce, params.echostr
        )
        if ret != 0:
            logger.error(f"[WecomBot] URL verify failed: ret={ret}")
            return "verify fail"
        if isinstance(echo, bytes):
            echo = echo.decode("utf-8")
        return echo

    def POST(self):
        channel = self._channel()
        if not channel._crypt:
            return "success"

        params = web.input(msg_signature="", timestamp="", nonce="")
        body = web.data()
        ret, plain = channel._crypt.decrypt_msg(
            body, params.msg_signature, params.timestamp, params.nonce
        )
        if ret != 0:
            logger.error(f"[WecomBot] callback decrypt failed: ret={ret}")
            return "success"

        try:
            data = json.loads(plain)
        except Exception as e:
            logger.error(f"[WecomBot] callback json parse failed: {e}")
            return "success"

        msgtype = data.get("msgtype", "")
        # Stream polls arrive ~1/s; logging each is noisy, so only log non-poll
        # callbacks here (poll completion is logged in the stream-poll handler).
        if msgtype != "stream":
            logger.debug(f"[WecomBot] callback received msgtype={msgtype}")

        try:
            if msgtype == "stream":
                reply = channel._callback_handle_stream_poll(data)
            elif msgtype == "event":
                event_type = data.get("event", {}).get("eventtype", "")
                logger.info(f"[WecomBot] callback event: {event_type}")
                reply = None
            elif msgtype in ("text", "image", "voice", "file", "video", "mixed"):
                reply = channel._callback_handle_message(data)
            else:
                logger.warning(f"[WecomBot] unsupported callback msgtype: {msgtype}")
                reply = None
        except Exception as e:
            logger.error(f"[WecomBot] callback handling error: {e}", exc_info=True)
            reply = None

        if not reply:
            # Empty reply package is acceptable.
            return "success"

        plain_reply = json.dumps(reply, ensure_ascii=False)
        ret, enc = channel._crypt.encrypt_msg(plain_reply, params.nonce, params.timestamp)
        if ret != 0:
            logger.error(f"[WecomBot] callback encrypt failed: ret={ret}")
            return "success"
        web.header("Content-Type", "application/json; charset=utf-8")
        return json.dumps(enc, ensure_ascii=False)
