"""
Weixin channel implementation.

Uses HTTP long-poll (getUpdates) to receive messages and sendMessage to reply.
Login via QR code scan through the ilink bot API.
"""

import json
import os
import threading
import time
import uuid

import requests

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.weixin.weixin_api import (
    WeixinApi, upload_media_to_cdn,
    DEFAULT_BASE_URL, CDN_BASE_URL,
)
from channel.weixin.weixin_message import WeixinMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from config import conf

MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY = 30
RETRY_DELAY = 2
SESSION_EXPIRED_ERRCODE = -14
TEXT_CHUNK_LIMIT = 4000
QR_LOGIN_TIMEOUT_S = 480
QR_MAX_REFRESHES = 10


def _load_credentials(cred_path: str) -> dict:
    """Load saved credentials from JSON file."""
    try:
        if os.path.exists(cred_path):
            with open(cred_path, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[Weixin] Failed to load credentials: {e}")
    return {}


def _save_credentials(cred_path: str, data: dict):
    """Save credentials to JSON file."""
    os.makedirs(os.path.dirname(cred_path), exist_ok=True)
    with open(cred_path, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(cred_path, 0o600)
    except Exception:
        pass


@singleton
class WeixinChannel(ChatChannel):

    LOGIN_STATUS_IDLE = "idle"
    LOGIN_STATUS_WAITING = "waiting_scan"
    LOGIN_STATUS_SCANNED = "scanned"
    LOGIN_STATUS_OK = "logged_in"

    def __init__(self):
        super().__init__()
        self.api = None
        self._stop_event = threading.Event()
        self._poll_thread = None
        self._context_tokens = {}  # user_id -> context_token
        self._received_msgs = ExpiredDict(60 * 60 * 7.1)
        self._get_updates_buf = ""
        self._credentials_path = ""
        self.login_status = self.LOGIN_STATUS_IDLE
        self._current_qr_url = ""

        conf()["single_chat_prefix"] = [""]

    # ── Lifecycle ──────────────────────────────────────────────────────

    def startup(self):
        self._stop_event.clear()

        base_url = conf().get("weixin_base_url", DEFAULT_BASE_URL)
        cdn_base_url = conf().get("weixin_cdn_base_url", CDN_BASE_URL)
        token = conf().get("weixin_token", "")

        self._credentials_path = os.path.expanduser(
            conf().get("weixin_credentials_path", "~/.weixin_cow_credentials.json")
        )

        if not token:
            creds = _load_credentials(self._credentials_path)
            token = creds.get("token", "")
            if creds.get("base_url"):
                base_url = creds["base_url"]

        if not token:
            token, base_url = self._login_with_retry(base_url)
            if not token:
                return

        self.api = WeixinApi(base_url=base_url, token=token, cdn_base_url=cdn_base_url)
        self.login_status = self.LOGIN_STATUS_OK

        logger.info(f"[Weixin] 微信通道已启动，凭证保存在 {self._credentials_path}，"
                     f"如需重新扫码登录请删除该文件后重启")
        self.report_startup_success()

        self._poll_loop()

    def _login_with_retry(self, base_url: str) -> tuple:
        """Attempt QR login, then wait for stop if failed.
        Returns (token, base_url) on success, or ("", "") if stopped."""
        logger.info("[Weixin] No token found, starting QR login...")
        self.login_status = self.LOGIN_STATUS_WAITING
        login_result = self._qr_login(base_url)
        if login_result:
            return login_result["token"], login_result.get("base_url", base_url)

        self.login_status = self.LOGIN_STATUS_IDLE
        if not self._stop_event.is_set():
            logger.info("[Weixin] QR login timed out, waiting for stop or reconnect...")
            print("  二维码登录超时，请通过控制台重新接入\n")
            self._stop_event.wait()

        logger.info("[Weixin] Login cancelled by stop event")
        return "", ""

    def stop(self):
        logger.info("[Weixin] stop() called")
        self._stop_event.set()

    def _relogin(self) -> bool:
        """Re-login after session expiry. Returns True on success."""
        base_url = self.api.base_url if self.api else DEFAULT_BASE_URL
        if os.path.exists(self._credentials_path):
            try:
                os.remove(self._credentials_path)
            except Exception:
                pass
        self.login_status = self.LOGIN_STATUS_WAITING
        result = self._qr_login(base_url)
        if not result:
            self.login_status = self.LOGIN_STATUS_IDLE
            return False
        self.api = WeixinApi(
            base_url=result.get("base_url", base_url),
            token=result["token"],
            cdn_base_url=self.api.cdn_base_url if self.api else CDN_BASE_URL,
        )
        self.login_status = self.LOGIN_STATUS_OK
        self._context_tokens.clear()
        return True

    # ── QR Login ───────────────────────────────────────────────────────

    @staticmethod
    def _print_qr(qrcode_url: str):
        """Print QR code to terminal for scanning."""
        print("\n" + "=" * 60)
        print("  请使用微信扫描二维码登录 (二维码约2分钟后过期)")
        print("=" * 60)
        try:
            import qrcode as qr_lib
            import io
            qr = qr_lib.QRCode(error_correction=qr_lib.constants.ERROR_CORRECT_L, box_size=1, border=1)
            qr.add_data(qrcode_url)
            qr.make(fit=True)
            buf = io.StringIO()
            qr.print_ascii(out=buf, invert=True)
            try:
                print(buf.getvalue())
            except UnicodeEncodeError:
                # Windows GBK terminals cannot render Unicode block characters
                print(f"\n  (终端不支持显示二维码，请使用链接扫码)")
                print(f"  二维码链接: {qrcode_url}\n")
        except ImportError:
            print(f"\n  二维码链接: {qrcode_url}")
            print("  (安装 'qrcode' 包可在终端显示二维码)\n")

    def _notify_cloud_qrcode(self, qrcode_url: str):
        """Send QR code URL to cloud console when running in cloud mode."""
        if not self.cloud_mode:
            return
        try:
            from common import cloud_client
            client = getattr(cloud_client, "chat_client", None)
            if client and getattr(client, "client_id", None):
                client.send_channel_qrcode("weixin", qrcode_url)
        except Exception as e:
            logger.warning(f"[Weixin] Failed to notify cloud QR code: {e}")

    def _notify_cloud_connected(self):
        """Send connected status to cloud console when login succeeds."""
        if not self.cloud_mode:
            return
        try:
            from common import cloud_client
            client = getattr(cloud_client, "chat_client", None)
            if client and getattr(client, "client_id", None):
                client.send_channel_status("weixin", "connected")
        except Exception as e:
            logger.warning(f"[Weixin] Failed to notify cloud connected: {e}")

    def _qr_login(self, base_url: str) -> dict:
        """Perform interactive QR code login. Returns dict with token/base_url or empty dict."""
        api = WeixinApi(base_url=base_url)
        try:
            qr_resp = api.fetch_qr_code()
        except Exception as e:
            logger.error(f"[Weixin] Failed to fetch QR code: {e}")
            return {}

        qrcode = qr_resp.get("qrcode", "")
        qrcode_url = qr_resp.get("qrcode_img_content", "")

        if not qrcode:
            logger.error("[Weixin] No QR code returned from server")
            return {}

        self._current_qr_url = qrcode_url
        logger.info(f"[Weixin] 微信二维码链接: {qrcode_url}")
        self._print_qr(qrcode_url)
        self._notify_cloud_qrcode(qrcode_url)
        print("  等待扫码...\n")

        scanned_printed = False
        refresh_count = 0
        deadline = time.time() + QR_LOGIN_TIMEOUT_S

        while not self._stop_event.is_set():
            if time.time() >= deadline:
                logger.warning(f"[Weixin] QR login timed out after {QR_LOGIN_TIMEOUT_S}s")
                print(f"\n  二维码登录超时（{QR_LOGIN_TIMEOUT_S}s），请重启后重试")
                break

            try:
                status_resp = api.poll_qr_status(qrcode)
            except Exception as e:
                logger.error(f"[Weixin] QR status poll error: {e}")
                return {}

            status = status_resp.get("status", "wait")

            if status == "wait":
                pass
            elif status == "scaned":
                self.login_status = self.LOGIN_STATUS_SCANNED
                if not scanned_printed:
                    print("  已扫码，请在手机上确认...")
                    scanned_printed = True
            elif status == "expired":
                refresh_count += 1
                if refresh_count >= QR_MAX_REFRESHES:
                    logger.warning(f"[Weixin] QR code refreshed {QR_MAX_REFRESHES} times, giving up")
                    print(f"\n  二维码已刷新 {QR_MAX_REFRESHES} 次仍未扫码，请重启后重试")
                    break
                print(f"  二维码已过期，正在刷新（{refresh_count}/{QR_MAX_REFRESHES}）...")
                try:
                    qr_resp = api.fetch_qr_code()
                    qrcode = qr_resp.get("qrcode", "")
                    qrcode_url = qr_resp.get("qrcode_img_content", "")
                    scanned_printed = False
                    self._current_qr_url = qrcode_url
                    logger.info(f"[Weixin] 微信二维码链接 ({refresh_count}/{QR_MAX_REFRESHES}): {qrcode_url}")
                    self._print_qr(qrcode_url)
                    self._notify_cloud_qrcode(qrcode_url)
                except Exception as e:
                    logger.error(f"[Weixin] QR refresh failed: {e}")
                    return {}
            elif status == "confirmed":
                bot_token = status_resp.get("bot_token", "")
                bot_id = status_resp.get("ilink_bot_id", "")
                result_base_url = status_resp.get("baseurl", base_url)
                user_id = status_resp.get("ilink_user_id", "")

                if not bot_token or not bot_id:
                    logger.error("[Weixin] Login confirmed but missing token/bot_id")
                    return {}

                self._current_qr_url = ""
                print(f"\n  ✅ 微信登录成功！bot_id={bot_id}")
                logger.info(f"[Weixin] Login confirmed: bot_id={bot_id}")
                self._notify_cloud_connected()

                creds = {
                    "token": bot_token,
                    "base_url": result_base_url,
                    "bot_id": bot_id,
                    "user_id": user_id,
                }
                _save_credentials(self._credentials_path, creds)
                logger.info(f"[Weixin] Credentials saved to {self._credentials_path}")

                return {"token": bot_token, "base_url": result_base_url}

            self._stop_event.wait(1)

        self._current_qr_url = ""
        if self._stop_event.is_set():
            logger.info("[Weixin] QR login cancelled by stop event")
        return {}

    # ── Long-poll loop ─────────────────────────────────────────────────

    def _poll_loop(self):
        """Main long-poll loop: getUpdates -> parse -> produce."""
        logger.info("[Weixin] Starting long-poll loop")
        consecutive_failures = 0

        while not self._stop_event.is_set():
            try:
                resp = self.api.get_updates(self._get_updates_buf)

                ret = resp.get("ret", 0)
                errcode = resp.get("errcode", 0)

                is_error = (ret != 0) or (errcode != 0)
                if is_error:
                    if errcode == SESSION_EXPIRED_ERRCODE or ret == SESSION_EXPIRED_ERRCODE:
                        logger.error("[Weixin] Session expired (errcode -14), starting re-login...")
                        if self._relogin():
                            logger.info("[Weixin] Re-login successful, resuming long-poll")
                            self._get_updates_buf = ""
                            consecutive_failures = 0
                            continue
                        else:
                            logger.error("[Weixin] Re-login failed, will retry in 5 minutes")
                            self._stop_event.wait(300)
                            continue

                    consecutive_failures += 1
                    errmsg = resp.get("errmsg", "")
                    logger.error(f"[Weixin] getUpdates error: ret={ret} errcode={errcode} "
                                 f"errmsg={errmsg} ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})")
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        consecutive_failures = 0
                        self._stop_event.wait(BACKOFF_DELAY)
                    else:
                        self._stop_event.wait(RETRY_DELAY)
                    continue

                consecutive_failures = 0

                # Update sync cursor
                new_buf = resp.get("get_updates_buf", "")
                if new_buf:
                    self._get_updates_buf = new_buf

                # Process messages
                msgs = resp.get("msgs", [])
                for raw_msg in msgs:
                    try:
                        self._process_message(raw_msg)
                    except Exception as e:
                        logger.error(f"[Weixin] Failed to process message: {e}", exc_info=True)

            except Exception as e:
                if self._stop_event.is_set():
                    break
                consecutive_failures += 1
                logger.error(f"[Weixin] getUpdates exception: {e} "
                             f"({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    self._stop_event.wait(BACKOFF_DELAY)
                else:
                    self._stop_event.wait(RETRY_DELAY)

        logger.info("[Weixin] Long-poll loop ended")

    def _process_message(self, raw_msg: dict):
        """Parse a single inbound message and produce to the handling queue."""
        msg_type = raw_msg.get("message_type", 0)
        if msg_type != 1:  # Only process USER messages (type=1)
            return

        msg_id = str(raw_msg.get("message_id", raw_msg.get("seq", "")))
        if self._received_msgs.get(msg_id):
            return
        self._received_msgs[msg_id] = True

        from_user = raw_msg.get("from_user_id", "")
        context_token = raw_msg.get("context_token", "")

        if context_token and from_user:
            self._context_tokens[from_user] = context_token

        cdn_base_url = self.api.cdn_base_url if self.api else CDN_BASE_URL
        try:
            wx_msg = WeixinMessage(raw_msg, cdn_base_url=cdn_base_url)
        except Exception as e:
            logger.error(f"[Weixin] Failed to parse WeixinMessage: {e}", exc_info=True)
            return

        logger.info(f"[Weixin] Received: from={from_user} ctype={wx_msg.ctype} "
                     f"content={str(wx_msg.content)[:50]}")

        # File cache logic
        from channel.file_cache import get_file_cache
        file_cache = get_file_cache()
        session_id = from_user

        if wx_msg.ctype == ContextType.IMAGE:
            if hasattr(wx_msg, "image_path") and wx_msg.image_path:
                file_cache.add(session_id, wx_msg.image_path, file_type="image")
                logger.info(f"[Weixin] Image cached for session {session_id}")
            return

        if wx_msg.ctype == ContextType.FILE:
            wx_msg.prepare()
            file_cache.add(session_id, wx_msg.content, file_type="file")
            logger.info(f"[Weixin] File cached for session {session_id}: {wx_msg.content}")
            return

        if wx_msg.ctype == ContextType.TEXT:
            cached_files = file_cache.get(session_id)
            if cached_files:
                refs = []
                for fi in cached_files:
                    ftype, fpath = fi["type"], fi["path"]
                    if ftype == "image":
                        refs.append(f"[图片: {fpath}]")
                    elif ftype == "video":
                        refs.append(f"[视频: {fpath}]")
                    else:
                        refs.append(f"[文件: {fpath}]")
                wx_msg.content = wx_msg.content + "\n" + "\n".join(refs)
                file_cache.clear(session_id)

        context = self._compose_context(
            wx_msg.ctype,
            wx_msg.content,
            isgroup=False,
            msg=wx_msg,
            no_need_at=True,
        )
        if context:
            self.produce(context)

    # ── _compose_context ───────────────────────────────────────────────

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        context = Context(ctype, content)
        context.kwargs = kwargs
        if "channel_type" not in context:
            context["channel_type"] = self.channel_type
        if "origin_ctype" not in context:
            context["origin_ctype"] = ctype

        cmsg = context["msg"]
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

    # ── Send reply ─────────────────────────────────────────────────────

    def send(self, reply: Reply, context: Context):
        receiver = context.get("receiver", "")
        msg = context.get("msg")
        context_token = self._get_context_token(receiver, msg)

        if not context_token:
            logger.error(f"[Weixin] No context_token for receiver={receiver}, cannot send")
            return

        if reply.type == ReplyType.TEXT:
            self._send_text(reply.content, receiver, context_token)
        elif reply.type in (ReplyType.IMAGE_URL, ReplyType.IMAGE):
            self._send_image(reply.content, receiver, context_token)
        elif reply.type == ReplyType.FILE:
            self._send_file(reply.content, receiver, context_token)
        elif reply.type in (ReplyType.VIDEO, ReplyType.VIDEO_URL):
            self._send_video(reply.content, receiver, context_token)
        else:
            logger.warning(f"[Weixin] Unsupported reply type: {reply.type}, fallback to text")
            self._send_text(str(reply.content), receiver, context_token)

    def _get_context_token(self, receiver: str, msg=None) -> str:
        """Get the context_token for a receiver, required for all sends."""
        if msg and hasattr(msg, "context_token") and msg.context_token:
            return msg.context_token
        return self._context_tokens.get(receiver, "")

    def _send_text(self, text: str, receiver: str, context_token: str):
        if len(text) <= TEXT_CHUNK_LIMIT:
            try:
                self.api.send_text(receiver, text, context_token)
                logger.debug(f"[Weixin] Text sent to {receiver}, len={len(text)}")
            except Exception as e:
                logger.error(f"[Weixin] Failed to send text: {e}")
            return

        chunks = self._split_text(text, TEXT_CHUNK_LIMIT)
        for i, chunk in enumerate(chunks):
            try:
                self.api.send_text(receiver, chunk, context_token)
                logger.debug(f"[Weixin] Text chunk {i+1}/{len(chunks)} sent to {receiver}, len={len(chunk)}")
            except Exception as e:
                logger.error(f"[Weixin] Failed to send text chunk {i+1}/{len(chunks)}: {e}")
                break
            if i < len(chunks) - 1:
                time.sleep(0.5)

    @staticmethod
    def _split_text(text: str, limit: int) -> list:
        """Split text into chunks, preferring to break at paragraph or line boundaries."""
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            cut = text.rfind("\n\n", 0, limit)
            if cut <= 0:
                cut = text.rfind("\n", 0, limit)
            if cut <= 0:
                cut = limit
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks

    def _send_image(self, img_path_or_url: str, receiver: str, context_token: str):
        local_path = self._resolve_media_path(img_path_or_url)
        if not local_path:
            self._send_text("[Image send failed: file not found]", receiver, context_token)
            return
        try:
            result = upload_media_to_cdn(self.api, local_path, receiver, media_type=1)
            self.api.send_image_item(
                to=receiver,
                context_token=context_token,
                encrypt_query_param=result["encrypt_query_param"],
                aes_key_b64=result["aes_key_b64"],
                ciphertext_size=result["ciphertext_size"],
            )
            logger.info(f"[Weixin] Image sent to {receiver}")
        except Exception as e:
            logger.error(f"[Weixin] Image send failed: {e}")
            self._send_text("[Image send failed]", receiver, context_token)

    def _send_file(self, file_path_or_url: str, receiver: str, context_token: str):
        local_path = self._resolve_media_path(file_path_or_url)
        if not local_path:
            self._send_text("[File send failed: file not found]", receiver, context_token)
            return
        try:
            result = upload_media_to_cdn(self.api, local_path, receiver, media_type=3)
            self.api.send_file_item(
                to=receiver,
                context_token=context_token,
                encrypt_query_param=result["encrypt_query_param"],
                aes_key_b64=result["aes_key_b64"],
                file_name=os.path.basename(local_path),
                file_size=result["raw_size"],
            )
            logger.info(f"[Weixin] File sent to {receiver}")
        except Exception as e:
            logger.error(f"[Weixin] File send failed: {e}")
            self._send_text("[File send failed]", receiver, context_token)

    def _send_video(self, video_path_or_url: str, receiver: str, context_token: str):
        local_path = self._resolve_media_path(video_path_or_url)
        if not local_path:
            self._send_text("[Video send failed: file not found]", receiver, context_token)
            return
        try:
            result = upload_media_to_cdn(self.api, local_path, receiver, media_type=2)
            self.api.send_video_item(
                to=receiver,
                context_token=context_token,
                encrypt_query_param=result["encrypt_query_param"],
                aes_key_b64=result["aes_key_b64"],
                ciphertext_size=result["ciphertext_size"],
            )
            logger.info(f"[Weixin] Video sent to {receiver}")
        except Exception as e:
            logger.error(f"[Weixin] Video send failed: {e}")
            self._send_text("[Video send failed]", receiver, context_token)

    @staticmethod
    def _resolve_media_path(path_or_url: str) -> str:
        """Resolve a file path or URL to a local file path. Downloads if needed."""
        if not path_or_url:
            return ""

        local_path = path_or_url
        if local_path.startswith("file://"):
            local_path = local_path[7:]

        if local_path.startswith(("http://", "https://")):
            try:
                resp = requests.get(local_path, timeout=60)
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "")
                ext = ".bin"
                if "jpeg" in ct or "jpg" in ct:
                    ext = ".jpg"
                elif "png" in ct:
                    ext = ".png"
                elif "gif" in ct:
                    ext = ".gif"
                elif "webp" in ct:
                    ext = ".webp"
                elif "mp4" in ct:
                    ext = ".mp4"
                elif "pdf" in ct:
                    ext = ".pdf"

                tmp_path = f"/tmp/wx_media_{uuid.uuid4().hex[:8]}{ext}"
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
                return tmp_path
            except Exception as e:
                logger.error(f"[Weixin] Failed to download media: {e}")
                return ""

        if os.path.exists(local_path):
            return local_path

        logger.warning(f"[Weixin] Media file not found: {local_path}")
        return ""
