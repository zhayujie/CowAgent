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
import threading
import time
import uuid

import requests
import websocket

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.wecom_bot.wecom_bot_message import WecomBotMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.ws_client_compat import websocket_app_run_forever
from config import conf

WECOM_WS_URL = "wss://openws.work.weixin.qq.com"
HEARTBEAT_INTERVAL = 30
MEDIA_CHUNK_SIZE = 512 * 1024  # 512KB per chunk (before base64 encoding)


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

        conf()["group_name_white_list"] = ["ALL_GROUP"]
        conf()["single_chat_prefix"] = [""]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self):
        self.bot_id = conf().get("wecom_bot_id", "")
        self.bot_secret = conf().get("wecom_bot_secret", "")

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

        try:
            wecom_msg = WecomBotMessage(body, is_group=is_group)
        except NotImplementedError as e:
            logger.warning(f"[WecomBot] {e}")
            return
        except Exception as e:
            logger.error(f"[WecomBot] Failed to parse message: {e}", exc_info=True)
            return

        wecom_msg.req_id = req_id

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
            return

        if wecom_msg.ctype == ContextType.FILE:
            wecom_msg.prepare()
            file_cache.add(session_id, wecom_msg.content, file_type="file")
            logger.info(f"[WecomBot] File cached for session {session_id}: {wecom_msg.content}")
            return

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
        if context:
            if req_id:
                context["on_event"] = self._make_stream_callback(req_id)
            self.produce(context)

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

        return on_event

    # ------------------------------------------------------------------
    # _compose_context (same pattern as feishu)
    # ------------------------------------------------------------------

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        context = Context(ctype, content)
        context.kwargs = kwargs
        if "channel_type" not in context:
            context["channel_type"] = self.channel_type
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

        return context

    # ------------------------------------------------------------------
    # Send reply
    # ------------------------------------------------------------------

    def send(self, reply: Reply, context: Context):
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
                tmp_path = f"/tmp/wecom_img_{uuid.uuid4().hex[:8]}{ext}"
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
                out_path = f"/tmp/wecom_fmt_{uuid.uuid4().hex[:8]}{correct_ext}"
                img.save(out_path, fmt)
                logger.info(f"[WecomBot] Image renamed: {file_path} -> {out_path} ({fmt})")
                return out_path

            # Unsupported format (WebP, GIF, BMP, etc.) — convert to PNG
            if img.mode == "RGBA":
                out_path = f"/tmp/wecom_fmt_{uuid.uuid4().hex[:8]}.png"
                img.save(out_path, "PNG")
            else:
                out_path = f"/tmp/wecom_fmt_{uuid.uuid4().hex[:8]}.jpg"
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

            out_path = f"/tmp/wecom_compressed_{uuid.uuid4().hex[:8]}.jpg"
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
                tmp_path = f"/tmp/wecom_file_{uuid.uuid4().hex[:8]}{ext}"
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
