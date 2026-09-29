"""
QQ Bot channel via WebSocket long connection.

Supports:
- Group chat (@bot), single chat (C2C), guild channel, guild DM
- Text / image / file message send & receive
- Heartbeat keep-alive and auto-reconnect with session resume
"""

import base64
import json
import os
import threading
import time

import requests
import websocket

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.qq.qq_message import QQMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.ws_client_compat import websocket_app_run_forever
from config import conf

# Rich media file_type constants
QQ_FILE_TYPE_IMAGE = 1
QQ_FILE_TYPE_VIDEO = 2
QQ_FILE_TYPE_VOICE = 3
QQ_FILE_TYPE_FILE = 4

QQ_API_BASE = "https://api.sgroup.qq.com"

# Intents: GROUP_AND_C2C_EVENT(1<<25) | PUBLIC_GUILD_MESSAGES(1<<30)
DEFAULT_INTENTS = (1 << 25) | (1 << 30)

# OpCode constants
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Resumable error codes
RESUMABLE_CLOSE_CODES = {4008, 4009}

# WebSocket transport-level keepalive. Without this the client never sends
# protocol pings, so a half-open connection (NAT/container network drop with no
# TCP FIN/RST) is never detected and _on_close never fires — the socket looks
# alive but no events arrive. ping_timeout closes the socket when a pong is
# missed, which routes into the existing _on_close reconnect path.
WS_PING_INTERVAL = 20
WS_PING_TIMEOUT = 10

# Heartbeat-ACK watchdog: if the QQ gateway stops acking our heartbeats for this
# many missed intervals, the connection is silently dead — force it closed so the
# reconnect path runs. Guards against a stall the transport ping alone can miss.
HEARTBEAT_ACK_TIMEOUT_FACTOR = 3


@singleton
class QQChannel(ChatChannel):

    def __init__(self):
        super().__init__()
        self.app_id = ""
        self.app_secret = ""

        self._access_token = ""
        self._token_expires_at = 0

        self._ws = None
        self._ws_thread = None
        self._heartbeat_thread = None
        self._connected = False
        self._stop_event = threading.Event()
        self._token_lock = threading.Lock()

        self._session_id = None
        self._last_seq = None
        self._heartbeat_interval = 45000
        # Timestamp of the last heartbeat ACK from the gateway, used by the
        # heartbeat loop to detect a silently-dead connection and force a
        # reconnect. Reset whenever a fresh connection starts sending heartbeats.
        self._last_heartbeat_ack = 0.0
        self._can_resume = False
        # Bumped on every stop so a superseded socket cannot reconnect itself.
        self._generation = 0
        # Last rejection from the QQ API, surfaced to the channel page so the
        # user sees the platform's reason instead of a bare "unavailable".
        self._last_api_error = ""

        self.received_msgs = ExpiredDict(60 * 60 * 7.1)
        self._msg_seq_counter = {}

        conf()["group_name_white_list"] = ["ALL_GROUP"]
        conf()["single_chat_prefix"] = [""]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self):
        if self._ws is not None:
            # Restarting the channel calls startup() again on the same instance.
            # Leaving the old socket open would make QQ push every event twice.
            logger.warning("[QQ] A session is already open, closing it before reconnecting")
            self.stop()

        self.app_id = self.cfg("qq_app_id", "")
        self.app_secret = self.cfg("qq_app_secret", "")

        if not self.app_id or not self.app_secret:
            err = "[QQ] qq_app_id and qq_app_secret are required"
            logger.error(err)
            self.report_startup_error(err)
            return

        self._refresh_access_token()
        if not self._access_token:
            err = f"[QQ] Failed to get initial access_token: {self._last_api_error}"
            logger.error(err)
            self.report_startup_error(err)
            return

        self._stop_event.clear()
        self._start_ws()

    def stop(self):
        logger.info("[QQ] stop() called")
        self._generation += 1
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._connected = False

    # ------------------------------------------------------------------
    # Access Token
    # ------------------------------------------------------------------

    def _refresh_access_token(self):
        try:
            resp = requests.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={"appId": self.app_id, "clientSecret": self.app_secret},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                # Credential errors arrive as HTTP 200 with a business code
                # ("机器人不存在", "appid invalid"), so the status says nothing.
                # Return without touching the expiry: the next call retries, and
                # a token that still works is not thrown away over a hiccup.
                self._last_api_error = resp.text
                logger.error(f"[QQ] Access token request refused: {resp.text}")
                return
            self._access_token = token
            expires_in = int(data.get("expires_in", 7200))
            self._token_expires_at = time.time() + expires_in - 60
            logger.debug(f"[QQ] Access token refreshed, expires_in={expires_in}s")
        except Exception as e:
            logger.error(f"[QQ] Failed to refresh access_token: {e}")

    def _get_access_token(self) -> str:
        with self._token_lock:
            if time.time() >= self._token_expires_at:
                self._refresh_access_token()
            return self._access_token

    def _get_auth_headers(self) -> dict:
        return {
            "Authorization": f"QQBot {self._get_access_token()}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # WebSocket connection
    # ------------------------------------------------------------------

    def _get_ws_url(self) -> str:
        try:
            resp = requests.get(
                f"{QQ_API_BASE}/gateway",
                headers=self._get_auth_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                # The body carries the platform's own code / message / trace_id,
                # the only thing that distinguishes an IP-allowlist rejection
                # from a bad token or an unreleased bot.
                self._last_api_error = f"status={resp.status_code}, body={resp.text}"
                logger.error(f"[QQ] Failed to get gateway URL: {self._last_api_error}")
                return ""
            url = resp.json().get("url", "")
            logger.debug(f"[QQ] Gateway URL: {url}")
            return url
        except Exception as e:
            self._last_api_error = str(e)
            logger.error(f"[QQ] Failed to get gateway URL: {e}")
            return ""

    def _start_ws(self):
        generation = self._generation
        ws_url = self._get_ws_url()
        if not ws_url:
            logger.error("[QQ] Cannot start WebSocket without gateway URL")
            self.report_startup_error(f"Failed to get gateway URL: {self._last_api_error}")
            return

        def _on_open(ws):
            logger.debug("[QQ] WebSocket connected, waiting for Hello...")

        def _on_message(ws, raw):
            try:
                data = json.loads(raw)
                self._handle_ws_message(data)
            except Exception as e:
                logger.error(f"[QQ] Failed to handle ws message: {e}", exc_info=True)

        def _on_error(ws, error):
            logger.error(f"[QQ] WebSocket error: {error}")

        def _on_close(ws, close_status_code, close_msg):
            logger.warning(f"[QQ] WebSocket closed: status={close_status_code}, msg={close_msg}")
            if self._generation != generation:
                # A newer session took over; reconnecting here would revive the
                # old one alongside it and double every incoming event.
                logger.info("[QQ] Superseded session closed, not reconnecting")
                return
            self._connected = False
            if not self._stop_event.is_set():
                if close_status_code in RESUMABLE_CLOSE_CODES and self._session_id:
                    self._can_resume = True
                    logger.info("[QQ] Will attempt resume in 3s...")
                    time.sleep(3)
                else:
                    self._can_resume = False
                    logger.info("[QQ] Will reconnect in 5s...")
                    time.sleep(5)
                if not self._stop_event.is_set():
                    self._start_ws()

        self._ws = websocket.WebSocketApp(
            ws_url,
            on_open=_on_open,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )

        def run_forever():
            try:
                websocket_app_run_forever(
                    self._ws,
                    ping_interval=WS_PING_INTERVAL,
                    ping_timeout=WS_PING_TIMEOUT,
                    reconnect=0,
                )
            except (SystemExit, KeyboardInterrupt):
                logger.info("[QQ] WebSocket thread interrupted")
            except Exception as e:
                logger.error(f"[QQ] WebSocket run_forever error: {e}")

        self._ws_thread = threading.Thread(target=run_forever, daemon=True)
        self._ws_thread.start()
        self._ws_thread.join()

    def _ws_send(self, data: dict):
        if self._ws:
            self._ws.send(json.dumps(data, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Identify & Resume & Heartbeat
    # ------------------------------------------------------------------

    def _send_identify(self):
        self._ws_send({
            "op": OP_IDENTIFY,
            "d": {
                "token": f"QQBot {self._get_access_token()}",
                "intents": DEFAULT_INTENTS,
                "shard": [0, 1],
                "properties": {
                    "$os": "linux",
                    "$browser": "chatgpt-on-wechat",
                    "$device": "chatgpt-on-wechat",
                },
            },
        })
        logger.debug(f"[QQ] Identify sent with intents={DEFAULT_INTENTS}")

    def _send_resume(self):
        self._ws_send({
            "op": OP_RESUME,
            "d": {
                "token": f"QQBot {self._get_access_token()}",
                "session_id": self._session_id,
                "seq": self._last_seq,
            },
        })
        logger.debug(f"[QQ] Resume sent: session_id={self._session_id}, seq={self._last_seq}")

    def _start_heartbeat(self, interval_ms: int):
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_interval = interval_ms
        interval_sec = interval_ms / 1000.0
        # Seed the ACK clock so the watchdog measures silence from now, not from
        # a stale value left by a previous connection.
        self._last_heartbeat_ack = time.time()
        ack_timeout = interval_sec * HEARTBEAT_ACK_TIMEOUT_FACTOR

        def heartbeat_loop():
            while not self._stop_event.is_set() and self._connected:
                try:
                    self._ws_send({
                        "op": OP_HEARTBEAT,
                        "d": self._last_seq,
                    })
                except Exception as e:
                    logger.warning(f"[QQ] Heartbeat send failed: {e}")
                    break
                self._stop_event.wait(interval_sec)
                # A live socket whose gateway has gone silent (no ACKs) still
                # passes ws_send, so detect the stall here and force a close so
                # the _on_close reconnect path runs.
                if self._stop_event.is_set() or not self._connected:
                    break
                if time.time() - self._last_heartbeat_ack > ack_timeout:
                    logger.warning(
                        f"[QQ] No heartbeat ACK for over {ack_timeout:.0f}s, "
                        f"connection appears dead, forcing reconnect"
                    )
                    ws = self._ws
                    if ws:
                        try:
                            ws.close()
                        except Exception:
                            pass
                    break

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    # ------------------------------------------------------------------
    # Incoming message dispatch
    # ------------------------------------------------------------------

    def _handle_ws_message(self, data: dict):
        op = data.get("op")
        d = data.get("d")
        t = data.get("t")
        s = data.get("s")

        if s is not None:
            self._last_seq = s

        if op == OP_HELLO:
            heartbeat_interval = d.get("heartbeat_interval", 45000) if d else 45000
            logger.debug(f"[QQ] Received Hello, heartbeat_interval={heartbeat_interval}ms")
            self._heartbeat_interval = heartbeat_interval
            if self._can_resume and self._session_id:
                self._send_resume()
            else:
                self._send_identify()

        elif op == OP_HEARTBEAT_ACK:
            self._last_heartbeat_ack = time.time()

        elif op == OP_HEARTBEAT:
            self._ws_send({"op": OP_HEARTBEAT, "d": self._last_seq})

        elif op == OP_RECONNECT:
            logger.warning("[QQ] Server requested reconnect")
            self._can_resume = True
            if self._ws:
                self._ws.close()

        elif op == OP_INVALID_SESSION:
            logger.warning("[QQ] Invalid session, re-identifying...")
            self._session_id = None
            self._can_resume = False
            time.sleep(2)
            self._send_identify()

        elif op == OP_DISPATCH:
            if t == "READY":
                self._session_id = d.get("session_id", "")
                user = d.get("user", {})
                bot_name = user.get('username', '')
                logger.info(f"[QQ] ✅ Connected successfully (bot={bot_name})")
                self._connected = True
                self._can_resume = False
                self._start_heartbeat(self._heartbeat_interval)
                self.report_startup_success()

            elif t == "RESUMED":
                logger.info("[QQ] Session resumed successfully")
                self._connected = True
                self._can_resume = False
                self._start_heartbeat(self._heartbeat_interval)

            elif t in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE",
                        "AT_MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE"):
                self._handle_msg_event(d, t)

            elif t in ("GROUP_ADD_ROBOT", "FRIEND_ADD"):
                logger.info(f"[QQ] Event: {t}")

            else:
                logger.debug(f"[QQ] Dispatch event: {t}")

    # ------------------------------------------------------------------
    # Message event handling
    # ------------------------------------------------------------------

    def _handle_msg_event(self, event_data: dict, event_type: str):
        msg_id = event_data.get("id", "")
        if self.received_msgs.get(msg_id):
            logger.debug(f"[QQ] Duplicate msg filtered: {msg_id}")
            return
        self.received_msgs[msg_id] = True

        try:
            qq_msg = QQMessage(event_data, event_type)
        except NotImplementedError as e:
            logger.warning(f"[QQ] {e}")
            return
        except Exception as e:
            logger.error(f"[QQ] Failed to parse message: {e}", exc_info=True)
            return

        is_group = qq_msg.is_group

        from channel.file_cache import get_file_cache
        file_cache = get_file_cache()

        session_id = self._compute_session_id(qq_msg, is_group)

        if qq_msg.ctype == ContextType.IMAGE:
            if hasattr(qq_msg, "image_path") and qq_msg.image_path:
                file_cache.add(session_id, qq_msg.image_path, file_type="image")
                logger.info(f"[QQ] Image cached for session {session_id}")
            return

        # A standalone file / video / voice message carries no text to answer,
        # so cache it (like an image) for the user's next question instead of
        # producing an empty context. Without this the attachment was silently
        # dropped and the agent "received nothing".
        if qq_msg.ctype == ContextType.FILE:
            fpath = getattr(qq_msg, "file_path", None)
            if fpath:
                ftype = getattr(qq_msg, "file_type", None) or "file"
                # FileCache understands image/video/other; map voice to a generic
                # file bucket so it still renders as [文件: ...] downstream.
                cache_type = ftype if ftype in ("image", "video") else "file"
                file_cache.add(session_id, fpath, file_type=cache_type)
                logger.info(f"[QQ] {ftype} cached for session {session_id}: {fpath}")
            else:
                logger.warning("[QQ] File message had no downloadable attachment")
            return

        if qq_msg.ctype == ContextType.TEXT:
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
                qq_msg.content = qq_msg.content + "\n" + "\n".join(file_refs)
                logger.info(f"[QQ] Attached {len(cached_files)} cached file(s)")
                file_cache.clear(session_id)

        context = self._compose_context(
            qq_msg.ctype,
            qq_msg.content,
            isgroup=is_group,
            msg=qq_msg,
            no_need_at=True,
        )
        if context:
            from agent.team_addressing import stamp_speaker_from_channel
            stamp_speaker_from_channel(self, context, qq_msg.content)
            self.produce(context)

    # ------------------------------------------------------------------
    # _compose_context
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_session_id(qq_msg, is_group: bool) -> str:
        """The conversation key for an inbound message.

        A group shares one session only when ``group_shared_session`` asks for
        it; otherwise every member gets their own, which is the rule the base
        ``chat_channel`` and the other group channels (dingtalk, discord,
        feishu, slack, telegram, wecom_bot) already apply. QQ keyed a group on
        the group id unconditionally, so the setting -- and its shipped default
        of False -- was a silent no-op here, and every member of a QQ group
        shared one conversation.
        """
        if not is_group:
            return qq_msg.from_user_id
        if conf().get("group_shared_session", True):
            return qq_msg.other_user_id
        return f"{qq_msg.from_user_id}:{qq_msg.other_user_id}"

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        context = Context(ctype, content)
        context.kwargs = kwargs
        if "channel_type" not in context:
            context["channel_type"] = self.channel_type
        self.stamp_instance_context(context)
        if "origin_ctype" not in context:
            # A voice message promoted to TEXT via QQ's official ASR carries
            # its VOICE origin on the message wrapper (QQMessage.origin_ctype);
            # surface it here so downstream plugins can tell voice-origin
            # messages apart, mirroring how other channels stamp origin_ctype.
            context["origin_ctype"] = getattr(kwargs.get("msg"), "origin_ctype", None) or ctype

        cmsg = context["msg"]

        context["session_id"] = self._compute_session_id(cmsg, cmsg.is_group)

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

        if not msg:
            # Active send (e.g. scheduled tasks), no original message to reply to
            self._active_send_text(reply.content if reply.type == ReplyType.TEXT else str(reply.content),
                                   receiver, is_group)
            return

        event_type = getattr(msg, "event_type", "")
        msg_id = getattr(msg, "msg_id", "")

        if reply.type == ReplyType.TEXT:
            self._send_text(reply.content, msg, event_type, msg_id)
        elif reply.type in (ReplyType.IMAGE_URL, ReplyType.IMAGE):
            self._send_image(reply.content, msg, event_type, msg_id)
        elif reply.type == ReplyType.FILE:
            if hasattr(reply, "text_content") and reply.text_content:
                self._send_text(reply.text_content, msg, event_type, msg_id)
                time.sleep(0.3)
            # The bridge stamps the original filename on the reply; a cloud URL's
            # last path segment is a random hash, so pass it through to keep the
            # document's real name (extension included).
            self._send_file(reply.content, msg, event_type, msg_id,
                            file_name=getattr(reply, "file_name", ""))
        elif reply.type in (ReplyType.VIDEO, ReplyType.VIDEO_URL):
            self._send_media(reply.content, msg, event_type, msg_id, QQ_FILE_TYPE_VIDEO)
        else:
            logger.warning(f"[QQ] Unsupported reply type: {reply.type}, falling back to text")
            self._send_text(str(reply.content), msg, event_type, msg_id)

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    def _get_next_msg_seq(self, msg_id: str) -> int:
        seq = self._msg_seq_counter.get(msg_id, 1)
        self._msg_seq_counter[msg_id] = seq + 1
        return seq

    def _build_msg_url_and_base_body(self, msg: QQMessage, event_type: str, msg_id: str):
        """Build the API URL and base body dict for sending a message."""
        if event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = msg._rawmsg.get("group_openid", "")
            url = f"{QQ_API_BASE}/v2/groups/{group_openid}/messages"
            body = {
                "msg_id": msg_id,
                "msg_seq": self._get_next_msg_seq(msg_id),
            }
            return url, body, "group", group_openid

        elif event_type == "C2C_MESSAGE_CREATE":
            user_openid = msg._rawmsg.get("author", {}).get("user_openid", "") or msg.from_user_id
            url = f"{QQ_API_BASE}/v2/users/{user_openid}/messages"
            body = {
                "msg_id": msg_id,
                "msg_seq": self._get_next_msg_seq(msg_id),
            }
            return url, body, "c2c", user_openid

        elif event_type == "AT_MESSAGE_CREATE":
            channel_id = msg._rawmsg.get("channel_id", "")
            url = f"{QQ_API_BASE}/channels/{channel_id}/messages"
            body = {"msg_id": msg_id}
            return url, body, "channel", channel_id

        elif event_type == "DIRECT_MESSAGE_CREATE":
            guild_id = msg._rawmsg.get("guild_id", "")
            url = f"{QQ_API_BASE}/dms/{guild_id}/messages"
            body = {"msg_id": msg_id}
            return url, body, "dm", guild_id

        return None, None, None, None

    def _post_message(self, url: str, body: dict, event_type: str) -> bool:
        """POST a message to the QQ API. Returns True on success so callers can
        fall back (e.g. Markdown -> plain text) when the platform rejects it."""
        try:
            resp = requests.post(url, json=body, headers=self._get_auth_headers(), timeout=10)
            if resp.status_code in (200, 201, 202, 204):
                logger.info(f"[QQ] Message sent successfully: event_type={event_type}")
                return True
            logger.error(f"[QQ] Failed to send message: status={resp.status_code}, "
                         f"body={resp.text}")
            return False
        except Exception as e:
            logger.error(f"[QQ] Send message error: {e}")
            return False

    # ------------------------------------------------------------------
    # Active send (no original message, e.g. scheduled tasks)
    # ------------------------------------------------------------------

    def _active_send_text(self, content: str, receiver: str, is_group: bool):
        """Send text without an original message (active push). QQ limits active messages to 4/month per user."""
        if not receiver:
            logger.warning("[QQ] No receiver for active send")
            return
        if is_group:
            url = f"{QQ_API_BASE}/v2/groups/{receiver}/messages"
        else:
            url = f"{QQ_API_BASE}/v2/users/{receiver}/messages"
        body = {
            "content": content,
            "msg_type": 0,
        }
        event_label = "GROUP_ACTIVE" if is_group else "C2C_ACTIVE"
        self._post_message(url, body, event_label)

    # ------------------------------------------------------------------
    # Send text
    # ------------------------------------------------------------------

    def _send_text(self, content: str, msg: QQMessage, event_type: str, msg_id: str):
        url, body, _, _ = self._build_msg_url_and_base_body(msg, event_type, msg_id)
        if not url:
            logger.warning(f"[QQ] Cannot send reply for event_type: {event_type}")
            return
        # QQ renders Markdown only via msg_type=2. Custom Markdown is open to all
        # bots in single (C2C) and group chat (since 2026-04-23), so use it there;
        # the guild channel / DM APIs need a template (or internal invite), so
        # those stay plain text. Empty content can't be a Markdown body either.
        if content and event_type in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"):
            md_body = dict(body)
            md_body["msg_type"] = 2
            md_body["markdown"] = {"content": content}
            # A bot whose Markdown is restricted (or content that trips QQ's
            # Markdown validator) rejects msg_type=2; fall back to plain text so
            # the user still gets the reply instead of nothing.
            if self._post_message(url, md_body, event_type):
                return
            logger.warning("[QQ] Markdown send rejected, retrying as plain text")
            body["msg_seq"] = self._get_next_msg_seq(msg_id)
        body["content"] = content
        body["msg_type"] = 0
        self._post_message(url, body, event_type)

    # ------------------------------------------------------------------
    # Rich media upload & send (image / video / file)
    # ------------------------------------------------------------------

    @staticmethod
    def _filename_from_url(file_url: str) -> str:
        """Best-effort filename from a URL: the last path segment if it has an
        extension. Returns '' when the URL ends in an opaque token (no '.')."""
        try:
            from urllib.parse import urlparse, unquote
            path = urlparse(file_url).path
            name = unquote(os.path.basename(path))
            return name if "." in name else ""
        except Exception:
            return ""

    def _upload_rich_media(self, file_url: str, file_type: int, msg: QQMessage,
                           event_type: str, file_name: str = "") -> str:
        """
        Upload media via QQ rich media API and return file_info.
        For group: POST /v2/groups/{group_openid}/files
        For c2c:   POST /v2/users/{openid}/files
        """
        if event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = msg._rawmsg.get("group_openid", "")
            upload_url = f"{QQ_API_BASE}/v2/groups/{group_openid}/files"
        elif event_type == "C2C_MESSAGE_CREATE":
            user_openid = (msg._rawmsg.get("author", {}).get("user_openid", "")
                           or msg.from_user_id)
            upload_url = f"{QQ_API_BASE}/v2/users/{user_openid}/files"
        else:
            logger.warning(f"[QQ] Rich media upload not supported for event_type: {event_type}")
            return ""

        upload_body = {
            "file_type": file_type,
            "url": file_url,
            "srv_send_msg": False,
        }
        # For documents, pass an explicit name so it doesn't render as "未命名".
        # The URL's last path segment is often a random hash, so prefer the
        # caller-supplied name when present.
        if file_type == QQ_FILE_TYPE_FILE:
            file_name = file_name or self._filename_from_url(file_url)
            if file_name:
                upload_body["file_name"] = file_name

        try:
            resp = requests.post(
                upload_url, json=upload_body,
                headers=self._get_auth_headers(), timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                file_info = data.get("file_info", "")
                logger.info(f"[QQ] Rich media uploaded: file_type={file_type}, "
                            f"file_uuid={data.get('file_uuid', '')}")
                return file_info
            else:
                logger.error(f"[QQ] Rich media upload failed: status={resp.status_code}, "
                             f"body={resp.text}")
                return ""
        except Exception as e:
            logger.error(f"[QQ] Rich media upload error: {e}")
            return ""

    def _upload_rich_media_base64(self, file_path: str, file_type: int, msg: QQMessage,
                                  event_type: str, file_name: str = "") -> str:
        """Upload local file via base64 file_data field."""
        if event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = msg._rawmsg.get("group_openid", "")
            upload_url = f"{QQ_API_BASE}/v2/groups/{group_openid}/files"
        elif event_type == "C2C_MESSAGE_CREATE":
            user_openid = (msg._rawmsg.get("author", {}).get("user_openid", "")
                           or msg.from_user_id)
            upload_url = f"{QQ_API_BASE}/v2/users/{user_openid}/files"
        else:
            logger.warning(f"[QQ] Rich media upload not supported for event_type: {event_type}")
            return ""

        try:
            with open(file_path, "rb") as f:
                file_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"[QQ] Failed to read file for upload: {e}")
            return ""

        upload_body = {
            "file_type": file_type,
            "file_data": file_data,
            "srv_send_msg": False,
        }
        # base64 carries no filename, so without file_name a document shows
        # with no extension. Only files (file_type=4) display a name. Prefer the
        # caller-supplied original name (the local tmp path may be a random one).
        if file_type == QQ_FILE_TYPE_FILE:
            file_name = file_name or os.path.basename(file_path)
            if file_name:
                upload_body["file_name"] = file_name

        try:
            resp = requests.post(
                upload_url, json=upload_body,
                headers=self._get_auth_headers(), timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                file_info = data.get("file_info", "")
                logger.info(f"[QQ] Rich media uploaded (base64): file_type={file_type}, "
                            f"file_uuid={data.get('file_uuid', '')}")
                return file_info
            else:
                logger.error(f"[QQ] Rich media upload (base64) failed: status={resp.status_code}, "
                             f"body={resp.text}")
                return ""
        except Exception as e:
            logger.error(f"[QQ] Rich media upload (base64) error: {e}")
            return ""

    def _send_media_msg(self, file_info: str, msg: QQMessage, event_type: str, msg_id: str):
        """Send a message with msg_type=7 (rich media) using file_info."""
        url, body, _, _ = self._build_msg_url_and_base_body(msg, event_type, msg_id)
        if not url:
            return
        body["msg_type"] = 7
        body["media"] = {"file_info": file_info}
        self._post_message(url, body, event_type)

    def _send_image(self, img_path_or_url: str, msg: QQMessage, event_type: str, msg_id: str):
        """Send image reply. Supports URL and local file path."""
        if event_type not in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"):
            self._send_text(str(img_path_or_url), msg, event_type, msg_id)
            return

        if img_path_or_url.startswith("file://"):
            img_path_or_url = img_path_or_url[7:]

        if img_path_or_url.startswith(("http://", "https://")):
            file_info = self._upload_rich_media(
                img_path_or_url, QQ_FILE_TYPE_IMAGE, msg, event_type)
        elif os.path.exists(img_path_or_url):
            file_info = self._upload_rich_media_base64(
                img_path_or_url, QQ_FILE_TYPE_IMAGE, msg, event_type)
        else:
            logger.error(f"[QQ] Image not found: {img_path_or_url}")
            self._send_text("[Image send failed]", msg, event_type, msg_id)
            return

        if file_info:
            self._send_media_msg(file_info, msg, event_type, msg_id)
        else:
            self._send_text("[Image upload failed]", msg, event_type, msg_id)

    def _send_file(self, file_path_or_url: str, msg: QQMessage, event_type: str, msg_id: str,
                   file_name: str = ""):
        """Send file reply."""
        if event_type not in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"):
            self._send_text(str(file_path_or_url), msg, event_type, msg_id)
            return

        if file_path_or_url.startswith("file://"):
            file_path_or_url = file_path_or_url[7:]

        if file_path_or_url.startswith(("http://", "https://")):
            file_info = self._upload_rich_media(
                file_path_or_url, QQ_FILE_TYPE_FILE, msg, event_type, file_name=file_name)
        elif os.path.exists(file_path_or_url):
            file_info = self._upload_rich_media_base64(
                file_path_or_url, QQ_FILE_TYPE_FILE, msg, event_type, file_name=file_name)
        else:
            logger.error(f"[QQ] File not found: {file_path_or_url}")
            self._send_text("[File send failed]", msg, event_type, msg_id)
            return

        if file_info:
            self._send_media_msg(file_info, msg, event_type, msg_id)
        else:
            self._send_text("[File upload failed]", msg, event_type, msg_id)

    def _send_media(self, path_or_url: str, msg: QQMessage, event_type: str,
                    msg_id: str, file_type: int):
        """Generic media send for video/voice etc."""
        if event_type not in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"):
            self._send_text(str(path_or_url), msg, event_type, msg_id)
            return

        if path_or_url.startswith("file://"):
            path_or_url = path_or_url[7:]

        if path_or_url.startswith(("http://", "https://")):
            file_info = self._upload_rich_media(path_or_url, file_type, msg, event_type)
        elif os.path.exists(path_or_url):
            file_info = self._upload_rich_media_base64(path_or_url, file_type, msg, event_type)
        else:
            logger.error(f"[QQ] Media not found: {path_or_url}")
            return

        if file_info:
            self._send_media_msg(file_info, msg, event_type, msg_id)
        else:
            logger.error(f"[QQ] Media upload failed: {path_or_url}")
