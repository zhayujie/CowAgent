"""
Weixin channel implementation.

Uses HTTP long-poll (getUpdates) to receive messages and sendMessage to reply.
Login via QR code scan through the ilink bot API.
"""

import glob
import json
import mimetypes
import os
import threading
import time
from typing import Tuple
from urllib.parse import unquote, urlparse

import requests

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.channel_instances import is_local_instance_id
from channel.weixin.weixin_api import (
    WeixinApi, upload_media_to_cdn,
    DEFAULT_BASE_URL, CDN_BASE_URL,
)
from channel.weixin.weixin_message import WeixinMessage
from common import state_dir
from common.expired_dict import ExpiredDict
from common.log import logger
from common.media_download import MAX_FILE_BYTES, remove_download, save_response
from common.singleton import singleton
from common.utils import is_cloud_deployment
from config import conf, get_weixin_credentials_path

# A reply's media URL comes from the model, and the download runs on the thread
# that is sending that reply. A socket timeout alone never fires on a server
# that keeps trickling bytes, so cap the whole transfer too - the same rule the
# other channels apply to remote replies.
_MAX_REMOTE_MEDIA_SECONDS = 300

MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY = 30
RETRY_DELAY = 2
SESSION_EXPIRED_ERRCODE = -14
TEXT_CHUNK_LIMIT = 4000
# How long a text message will wait for a concurrently-sent image/file to
# finish downloading into the cache before being handled without it.
PENDING_MEDIA_WAIT_S = 3.0
PENDING_MEDIA_POLL_S = 0.1
QR_LOGIN_TIMEOUT_S = 480
QR_MAX_REFRESHES = 10
# Serializes the "is this login free / take it" pair across instances.
_ADOPT_LOCK = threading.Lock()
# token -> instance of every Weixin channel logged in in this process. Guarded
# by _ADOPT_LOCK.
_ACTIVE_LOGINS = {}

# mimetypes lacks Office formats on older Pythons and on Windows depends on
# the registry, so common types are pinned here.
_CONTENT_TYPE_EXTS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/amr": ".amr",
    "audio/silk": ".silk",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/x-7z-compressed": ".7z",
    "application/x-rar-compressed": ".rar",
    "application/vnd.rar": ".rar",
    "application/gzip": ".gz",
    "application/x-tar": ".tar",
    "application/json": ".json",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/html": ".html",
}


def _valid_ext(ext: str) -> str:
    ext = (ext or "").lower()
    if 1 < len(ext) <= 12 and ext[1:].isalnum():
        return ext
    return ""


def _filename_from_disposition(disposition: str) -> str:
    """Extract the filename from a Content-Disposition header, if any."""
    if not disposition:
        return ""
    for part in disposition.split(";"):
        key, _, value = part.strip().partition("=")
        key = key.strip().lower()
        value = value.strip().strip('"')
        if key == "filename*" and value:
            # RFC 5987: charset'lang'percent-encoded-name
            return unquote(value.split("'", 2)[-1])
        if key == "filename" and value:
            return value
    return ""


def _guess_download_ext(url: str, headers) -> str:
    """Pick a file extension for a downloaded URL so the saved file keeps its type."""
    ext = _valid_ext(os.path.splitext(urlparse(url).path)[1])
    if ext:
        return ext
    ext = _valid_ext(os.path.splitext(
        _filename_from_disposition(headers.get("Content-Disposition", "")))[1])
    if ext:
        return ext
    ct = headers.get("Content-Type", "").split(";")[0].strip().lower()
    ext = _CONTENT_TYPE_EXTS.get(ct) or _valid_ext(mimetypes.guess_extension(ct) or "")
    return ext or ".bin"


def _open_media_response(url: str, timeout: float = 60):
    """Open a reply's media URL, guarding it like the other channels do.

    The URL came from the model, not from the user, so when the SSRF guard is
    on the target - and every redirect hop - must resolve to a public address.
    The response is left open for the caller to stream into a file.
    """
    from agent.tools.utils.url_safety import (
        _ssrf_protection_enabled, safe_get, validate_url_safe,
    )

    if _ssrf_protection_enabled():
        # safe_get only re-checks the hops it follows, so the first one is
        # validated here (same order as common.media_download._open).
        validate_url_safe(url)
        response = safe_get(url, timeout=timeout, stream=True)
    else:
        response = requests.get(url, timeout=timeout, stream=True)
    try:
        response.raise_for_status()
    except BaseException:
        # Only a body that opened successfully is handed to save_response,
        # so a rejected status must release its stream here.
        try:
            response.close()
        except Exception:
            pass
        raise
    return response


def _console_print(*args, **kwargs):
    """print() that never raises.

    Console output is cosmetic, but a Windows GBK console rejects characters
    such as emoji with UnicodeEncodeError; raised mid-login it would discard a
    login the server has already confirmed.
    """
    try:
        print(*args, **kwargs)
    except (UnicodeEncodeError, OSError, ValueError):
        pass


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
    """Atomically save credentials to JSON file (tmp + rename)."""
    os.makedirs(os.path.dirname(cred_path), exist_ok=True)
    tmp_path = f"{cred_path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(tmp_path, 0o600)
    except Exception:
        pass
    os.replace(tmp_path, cred_path)


@singleton
class WeixinChannel(ChatChannel):

    # ilink bot protocol has no outbound voice item; deliver TTS as a file.
    NOT_SUPPORT_REPLYTYPE = []

    LOGIN_STATUS_IDLE = "idle"
    LOGIN_STATUS_WAITING = "waiting_scan"
    LOGIN_STATUS_SCANNED = "scanned"
    LOGIN_STATUS_OK = "logged_in"

    def __init__(self):
        super().__init__()
        self.api = None
        self._stop_event = threading.Event()
        self._poll_thread = None
        # user_id -> context_token. Guarded by _context_tokens_lock for any
        # mutation that races with disk persistence.
        self._context_tokens = {}
        self._context_tokens_lock = threading.Lock()
        self._received_msgs = ExpiredDict(60 * 60 * 7.1)
        # session_id -> deadline(ts) until which an inbound image/file is
        # expected to finish downloading into the file cache. Lets a text
        # message that arrives together with (but slightly ahead of) an image
        # wait for the media path instead of reaching the agent without it.
        self._pending_media = {}
        self._pending_media_lock = threading.Lock()
        self._get_updates_buf = ""
        self._credentials_path = ""
        self.login_status = self.LOGIN_STATUS_IDLE
        self._current_qr_url = ""
        # Why the last QR login attempt ended without a login, for status reports.
        self._login_error = ""

        conf()["single_chat_prefix"] = [""]

    # ── Lifecycle ──────────────────────────────────────────────────────

    def startup(self):
        self._stop_event.clear()

        base_url = self.cfg("weixin_base_url", DEFAULT_BASE_URL)
        cdn_base_url = conf().get("weixin_cdn_base_url", CDN_BASE_URL)
        token = self.cfg("weixin_token", "")

        # Isolate the token file per instance so two Weixin accounts running in
        # one process don't overwrite each other's credentials. instance_id is
        # empty for a single-instance (legacy) channel -> the legacy path.
        self._credentials_path = get_weixin_credentials_path(
            getattr(self, "instance_id", "") or ""
        )

        # Always load credentials so we can restore context_tokens even when
        # the bot token itself comes from config.
        creds = _load_credentials(self._credentials_path)
        if not token:
            token = creds.get("token", "")
            if creds.get("base_url"):
                base_url = creds["base_url"]

        # A login can predate this instance's own file: the scan flow writes to
        # the default (id-less) file, and a channel that used to run without an
        # instance id left its login there too. Adopt it once and copy it into
        # this instance's file, but only while no other instance has claimed it
        # — that claim is what stops a second instance from ending up on the
        # first one's account instead of scanning for its own.
        # Claiming is checked and recorded under one lock: instances start on
        # their own threads, and two of them reading "unclaimed" before either
        # has written would put both on the same account.
        instance_id = getattr(self, "instance_id", "") or ""
        if not token and instance_id and self._may_adopt_default_login(instance_id):
            with _ADOPT_LOCK:
                legacy = _load_credentials(get_weixin_credentials_path())
                if legacy.get("token") and self._login_unclaimed(legacy["token"]):
                    token = legacy["token"]
                    if legacy.get("base_url"):
                        base_url = legacy["base_url"]
                    creds = self._adopt_credentials(legacy, creds)
                    logger.info(
                        f"[Weixin] instance '{instance_id}' adopted the token from the "
                        f"default credentials file"
                    )

        # Restore persisted context_tokens so scheduler can deliver pushes
        # immediately after restart, without waiting for the user to ping
        # the bot first.
        self._restore_context_tokens_from_creds(creds)

        if not token:
            token, base_url = self._login_with_retry(base_url)
            if not token:
                return

        self.api = WeixinApi(base_url=base_url, token=token, cdn_base_url=cdn_base_url)
        self._hold_login(token)
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
            logger.info("[Weixin] QR login ended without success, waiting for stop or reconnect...")
            _console_print("  二维码登录超时，请通过控制台重新接入\n")
            self._notify_cloud_status("error", self._login_error or "QR login timed out, please reconnect")
            self._stop_event.wait()

        logger.info("[Weixin] Login cancelled by stop event")
        return "", ""

    def stop(self):
        logger.info("[Weixin] stop() called")
        self._stop_event.set()
        self._hold_login("")

    def _relogin(self) -> bool:
        """Re-login after session expiry. Returns True on success."""
        base_url = self.api.base_url if self.api else DEFAULT_BASE_URL
        # Clearing the whole credentials file is intentional: the new login
        # will issue a fresh `token` and persisted context_tokens belong to
        # the previous bot identity, so they must not survive.
        with self._context_tokens_lock:
            self._context_tokens.clear()
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
        self._hold_login(result["token"])
        self.login_status = self.LOGIN_STATUS_OK
        return True

    # ── Context token persistence ──────────────────────────────────────
    # ilink requires every outbound send to echo the context_token from the
    # user's latest inbound message. We mirror the in-memory map into the
    # credentials JSON so scheduled pushes survive process restarts.
    # All mutation + disk IO is serialized via _context_tokens_lock so that
    # concurrent updates can never lose each other's writes.

    @staticmethod
    def _may_adopt_default_login(instance_id: str) -> bool:
        """Whether this instance may take over the login in the default file.

        An id minted on this machine is the channel the local scan flow was
        for. An id provided from outside stands for a separately provisioned
        bot, which scans for its own account — except on a cloud deployment,
        where it is the same channel that used to run without an id.
        """
        return is_local_instance_id(instance_id, "weixin") or is_cloud_deployment()

    def _login_key(self) -> str:
        return getattr(self, "instance_id", "") or "weixin"

    def _hold_login(self, token: str) -> None:
        """Record *token* as this instance's login in this process ("" to release)."""
        key = self._login_key()
        with _ADOPT_LOCK:
            for held, owner in list(_ACTIVE_LOGINS.items()):
                if owner == key:
                    del _ACTIVE_LOGINS[held]
            if token:
                _ACTIVE_LOGINS[token] = key

    def _configured_logins(self) -> set:
        """Tokens other Weixin instances carry in their configured credentials.

        A login scanned from the console lives there rather than in the
        instance's own credentials file, so the files alone miss it.
        """
        from agent import team
        from channel.channel_instances import resolve_channel_instances

        own = self._login_key()
        tokens = set()
        for inst in resolve_channel_instances(team.resolve(conf())):
            if inst.channel_type != "weixin" or inst.instance_id == own:
                continue
            token = (inst.credentials or {}).get("weixin_token")
            if token:
                tokens.add(token)
        return tokens

    def _login_unclaimed(self, token: str) -> bool:
        """Whether no other instance already runs on *token*.

        Caller holds _ADOPT_LOCK. A login is taken when another instance runs
        on it in this process, carries it in its configured credentials, or has
        copied it into its own credentials file. Unreadable surroundings count
        as claimed: sharing one account between two instances costs a silent
        misroute of every message, while the alternative is a scan the user can
        repeat.
        """
        owner = _ACTIVE_LOGINS.get(token)
        if owner and owner != self._login_key():
            return False
        try:
            if token in self._configured_logins():
                return False
        except Exception:
            return False
        base = get_weixin_credentials_path()
        root, ext = os.path.splitext(base)
        try:
            siblings = glob.glob(f"{root}.*{ext or '.json'}")
        except Exception:
            return False
        for path in siblings:
            if os.path.abspath(path) == os.path.abspath(self._credentials_path):
                continue
            if _load_credentials(path).get("token") == token:
                return False
        return True

    def _adopt_credentials(self, source: dict, own: dict) -> dict:
        """Copy a login adopted from *source* into this instance's own file.

        Anything this instance already persisted wins over the source; the
        merged result is returned so the caller can keep using it. Best-effort:
        a failed write only costs a re-adopt on the next start.
        """
        merged = dict(source or {})
        merged.update({k: v for k, v in (own or {}).items() if v})
        try:
            _save_credentials(self._credentials_path, merged)
        except Exception as e:
            logger.warning(f"[Weixin] Failed to persist adopted credentials: {e}")
        return merged

    def _restore_context_tokens_from_creds(self, creds: dict) -> None:
        if not isinstance(creds, dict):
            return
        tokens = creds.get("context_tokens")
        if not isinstance(tokens, dict):
            return
        restored = 0
        with self._context_tokens_lock:
            for user_id, token in tokens.items():
                if isinstance(user_id, str) and isinstance(token, str) and token:
                    self._context_tokens[user_id] = token
                    restored += 1
        if restored:
            logger.info(f"[Weixin] Restored {restored} context_tokens from credentials")

    def _persist_context_tokens_locked(self) -> None:
        """Flush the token map to disk. Caller must hold _context_tokens_lock."""
        if not self._credentials_path:
            return
        try:
            creds = _load_credentials(self._credentials_path) or {}
            creds["context_tokens"] = dict(self._context_tokens)
            _save_credentials(self._credentials_path, creds)
        except Exception as e:
            logger.warning(f"[Weixin] Failed to persist context_tokens: {e}")

    def _update_context_token(self, user_id: str, token: str) -> None:
        """Update the in-memory token for a user; flush to disk only on change."""
        if not user_id or not token:
            return
        with self._context_tokens_lock:
            if self._context_tokens.get(user_id) == token:
                return
            self._context_tokens[user_id] = token
            self._persist_context_tokens_locked()

    def _invalidate_context_token(self, user_id: str) -> None:
        """Drop the cached token for a user (used after -14 / send rejection)."""
        if not user_id:
            return
        with self._context_tokens_lock:
            if user_id not in self._context_tokens:
                return
            del self._context_tokens[user_id]
            logger.info(f"[Weixin] Invalidated stale context_token for {user_id}")
            self._persist_context_tokens_locked()

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
                print("\n  (终端不支持显示二维码，请使用链接扫码)")
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
                client.send_channel_qrcode(
                    "weixin", qrcode_url, channel_id=self._cloud_channel_id()
                )
        except Exception as e:
            logger.warning(f"[Weixin] Failed to notify cloud QR code: {e}")

    def _notify_cloud_connected(self):
        """Send connected status to cloud console when login succeeds."""
        self._notify_cloud_status("connected")

    def _notify_cloud_status(self, status: str, error: str = None):
        """Report a login state change, replacing any QR code reported before."""
        if not getattr(self, "cloud_mode", False):
            return
        try:
            from common import cloud_client
            client = getattr(cloud_client, "chat_client", None)
            if client and getattr(client, "client_id", None):
                client.send_channel_status(
                    "weixin", status, error, channel_id=self._cloud_channel_id()
                )
        except Exception as e:
            logger.warning(f"[Weixin] Failed to notify cloud status '{status}': {e}")

    def _cloud_channel_id(self) -> str:
        """The platform-issued instance id, or "" for the legacy single channel.

        The bare type name is what a legacy install runs under; reporting it as
        an id would make the control plane look up a channel that never existed.
        """
        instance_id = getattr(self, "instance_id", "") or ""
        return "" if instance_id in ("", "weixin", "wx") else instance_id

    def _end_qr_login(self, reason: str) -> dict:
        """Close a QR login attempt that did not log in, keeping *reason* for status reports."""
        self._login_error = reason
        self._current_qr_url = ""
        return {}

    def _qr_login(self, base_url: str) -> dict:
        """Perform interactive QR code login. Returns dict with token/base_url or empty dict."""
        self._login_error = ""
        api = WeixinApi(base_url=base_url)
        try:
            qr_resp = api.fetch_qr_code()
        except Exception as e:
            logger.error(f"[Weixin] Failed to fetch QR code: {e}")
            return self._end_qr_login(f"Failed to fetch QR code: {e}")

        qrcode = qr_resp.get("qrcode", "")
        qrcode_url = qr_resp.get("qrcode_img_content", "")

        if not qrcode:
            logger.error(f"[Weixin] No QR code returned from server: {qr_resp}")
            return self._end_qr_login("No QR code returned from server")

        self._current_qr_url = qrcode_url
        logger.info(f"[Weixin] 微信二维码链接: {qrcode_url}")
        self._print_qr(qrcode_url)
        self._notify_cloud_qrcode(qrcode_url)
        _console_print("  等待扫码...\n")

        # Status polling may be redirected to another host after the scan; a
        # fresh code always starts over on the original one.
        poll_api = api
        scanned_printed = False
        refresh_count = 0
        deadline = time.time() + QR_LOGIN_TIMEOUT_S

        while not self._stop_event.is_set():
            if time.time() >= deadline:
                logger.warning(f"[Weixin] QR login timed out after {QR_LOGIN_TIMEOUT_S}s")
                _console_print(f"\n  二维码登录超时（{QR_LOGIN_TIMEOUT_S}s），请重启后重试")
                return self._end_qr_login("QR login timed out, please reconnect")

            try:
                status_resp = poll_api.poll_qr_status(qrcode)
            except Exception as e:
                logger.error(f"[Weixin] QR status poll error: {e}")
                return self._end_qr_login(f"QR status poll failed: {e}")

            status = status_resp.get("status", "wait")

            if status == "wait":
                pass
            elif status == "scaned":
                self.login_status = self.LOGIN_STATUS_SCANNED
                if not scanned_printed:
                    _console_print("  已扫码，请在手机上确认...")
                    scanned_printed = True
            elif status == "scaned_but_redirect":
                redirect_host = (status_resp.get("redirect_host") or "").strip()
                if redirect_host:
                    poll_api = WeixinApi(base_url=f"https://{redirect_host}")
                    logger.info(f"[Weixin] QR status polling redirected to {redirect_host}")
                else:
                    logger.warning("[Weixin] scaned_but_redirect without redirect_host, keep current host")
            elif status in ("expired", "verify_code_blocked"):
                refresh_count += 1
                if refresh_count >= QR_MAX_REFRESHES:
                    logger.warning(f"[Weixin] QR code refreshed {QR_MAX_REFRESHES} times, giving up")
                    _console_print(f"\n  二维码已刷新 {QR_MAX_REFRESHES} 次仍未扫码，请重启后重试")
                    return self._end_qr_login("QR code was not scanned in time, please reconnect")
                if status == "verify_code_blocked":
                    logger.warning("[Weixin] Pairing code blocked after wrong attempts, refreshing QR code")
                _console_print(f"  二维码已过期，正在刷新（{refresh_count}/{QR_MAX_REFRESHES}）...")
                try:
                    qr_resp = api.fetch_qr_code()
                    qrcode = qr_resp.get("qrcode", "")
                    qrcode_url = qr_resp.get("qrcode_img_content", "")
                    # A 200 with an error body has no qrcode; polling an empty
                    # code only ever reports "wait".
                    if not qrcode:
                        logger.error(
                            f"[Weixin] QR refresh returned no qrcode; stopping login: {qr_resp}"
                        )
                        return self._end_qr_login("No QR code returned from server")
                    poll_api = api
                    scanned_printed = False
                    self._current_qr_url = qrcode_url
                    logger.info(f"[Weixin] 微信二维码链接 ({refresh_count}/{QR_MAX_REFRESHES}): {qrcode_url}")
                    self._print_qr(qrcode_url)
                    self._notify_cloud_qrcode(qrcode_url)
                except Exception as e:
                    logger.error(f"[Weixin] QR refresh failed: {e}")
                    return self._end_qr_login(f"QR refresh failed: {e}")
            elif status == "need_verifycode":
                # The pairing code shown on the phone has no input path here, so
                # waiting would only run into the timeout.
                logger.warning("[Weixin] Login requires a pairing code, which is not supported")
                _console_print("\n  微信要求输入配对码，当前版本暂不支持，请稍后重试")
                return self._end_qr_login("Weixin requires a pairing code for this login, please retry later")
            elif status == "binded_redirect":
                logger.warning("[Weixin] Scanned account is already bound, no new credentials issued")
                return self._end_qr_login("This Weixin account is already connected elsewhere")
            elif status == "confirmed":
                bot_token = status_resp.get("bot_token", "")
                bot_id = status_resp.get("ilink_bot_id", "")
                result_base_url = status_resp.get("baseurl") or base_url
                user_id = status_resp.get("ilink_user_id", "")

                if not bot_token or not bot_id:
                    logger.error("[Weixin] Login confirmed but missing token/bot_id")
                    return self._end_qr_login("Login confirmed but no credentials returned")

                self._current_qr_url = ""
                _console_print(f"\n  ✅ 微信登录成功！bot_id={bot_id}")
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
            else:
                logger.debug(f"[Weixin] Unhandled QR status '{status}', keep polling")

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
                        if self._stop_event.is_set():
                            break
                        # No automatic retry: every round issues fresh QR codes
                        # nobody is scanning, and a stream of those from one
                        # network is what upstream risk control flags. A new
                        # attempt starts when the channel is restarted.
                        logger.error("[Weixin] Re-login failed, waiting for reconnect")
                        _console_print("  微信登录已失效且重新扫码未完成，请通过控制台重新接入或重启\n")
                        self._notify_cloud_status(
                            "error",
                            self._login_error or "Weixin session expired, please reconnect",
                        )
                        self._stop_event.wait()
                        break

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

                # Process messages. Media (image/file/video) messages are
                # handled before text ones within the same batch so that a
                # text message sent together with an image finds the image
                # already in the cache (the media download would otherwise let
                # the text win the race and reach the agent without the media).
                msgs = resp.get("msgs", [])
                for raw_msg in self._order_msgs(msgs):
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

    @staticmethod
    def _raw_msg_has_media(raw_msg: dict) -> bool:
        """Whether a raw message carries a media item (image/voice/file/video)."""
        from channel.weixin.weixin_message import (
            ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO,
        )
        media_types = {ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO}
        for item in raw_msg.get("item_list", []):
            if item.get("type") in media_types:
                return True
            ref_mi = item.get("ref_msg", {}).get("message_item", {})
            if ref_mi.get("type") in media_types:
                return True
        return False

    def _order_msgs(self, msgs: list) -> list:
        """Stable-sort a batch so media-bearing messages come before pure text.

        Only USER messages (message_type == 1) are considered media candidates;
        ordering is otherwise stable to preserve the original sequence.
        """
        def is_media(m):
            return m.get("message_type", 0) == 1 and self._raw_msg_has_media(m)
        media = [m for m in msgs if is_media(m)]
        rest = [m for m in msgs if not is_media(m)]
        return media + rest

    def _mark_pending_media(self, session_id: str):
        with self._pending_media_lock:
            self._pending_media[session_id] = time.time() + PENDING_MEDIA_WAIT_S

    def _clear_pending_media(self, session_id: str):
        with self._pending_media_lock:
            self._pending_media.pop(session_id, None)

    def _wait_for_pending_media(self, session_id: str, file_cache):
        """Block briefly if a media download for this session is in flight.

        Handles the case where an image and a text message are delivered in
        separate poll batches and the text is processed first: give the media
        a short window to land in the cache before the text reaches the agent.
        """
        with self._pending_media_lock:
            deadline = self._pending_media.get(session_id)
        if not deadline:
            return
        while time.time() < deadline:
            if file_cache.get(session_id):
                return
            time.sleep(PENDING_MEDIA_POLL_S)

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
            self._update_context_token(from_user, context_token)

        session_id = from_user
        # Mark media as in-flight *before* the (slow) synchronous download so a
        # text message from the same user that is processed first can wait for
        # it (see _wait_for_pending_media).
        has_media = self._raw_msg_has_media(raw_msg)
        if has_media and session_id:
            self._mark_pending_media(session_id)

        cdn_base_url = self.api.cdn_base_url if self.api else CDN_BASE_URL
        try:
            wx_msg = WeixinMessage(raw_msg, cdn_base_url=cdn_base_url)
        except Exception as e:
            logger.error(f"[Weixin] Failed to parse WeixinMessage: {e}", exc_info=True)
            if has_media and session_id:
                self._clear_pending_media(session_id)
            return

        logger.info(f"[Weixin] Received: from={from_user} ctype={wx_msg.ctype} "
                     f"content={str(wx_msg.content)[:50]}")

        # File cache logic
        from channel.file_cache import get_file_cache
        file_cache = get_file_cache()

        if wx_msg.ctype == ContextType.IMAGE:
            if hasattr(wx_msg, "image_path") and wx_msg.image_path:
                file_cache.add(session_id, wx_msg.image_path, file_type="image")
                logger.info(f"[Weixin] Image cached for session {session_id}")
            self._clear_pending_media(session_id)
            return

        if wx_msg.ctype == ContextType.FILE:
            wx_msg.prepare()
            # A failed download leaves content pointing at a file that does not exist.
            if not wx_msg.content or not os.path.exists(wx_msg.content):
                logger.warning(
                    "[Weixin] File download did not land, not caching: %s",
                    wx_msg.content,
                )
                self._clear_pending_media(session_id)
                return
            file_cache.add(session_id, wx_msg.content, file_type="file")
            logger.info(f"[Weixin] File cached for session {session_id}: {wx_msg.content}")
            self._clear_pending_media(session_id)
            return

        if wx_msg.ctype == ContextType.TEXT:
            if has_media:
                # This message already carries its own media inline; its ref was
                # attached during parsing, so just release the in-flight marker.
                self._clear_pending_media(session_id)
            else:
                # A media message from the same user may still be downloading (it
                # can arrive in a separate poll batch); wait briefly so its path
                # gets attached instead of the agent answering without the image.
                self._wait_for_pending_media(session_id, file_cache)
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
            from agent.team_addressing import stamp_speaker_from_channel
            stamp_speaker_from_channel(self, context, wx_msg.content)
            self.produce(context)

    # ── _compose_context ───────────────────────────────────────────────

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        context = Context(ctype, content)
        context.kwargs = kwargs
        if "channel_type" not in context:
            context["channel_type"] = self.channel_type
        self.stamp_instance_context(context)
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
            if "desire_rtype" not in context and conf().get("always_reply_voice"):
                context["desire_rtype"] = ReplyType.VOICE

        elif ctype == ContextType.VOICE:
            if "desire_rtype" not in context and (
                conf().get("voice_reply_voice") or conf().get("always_reply_voice")
            ):
                context["desire_rtype"] = ReplyType.VOICE

        return context

    # ── Send reply ─────────────────────────────────────────────────────

    def send(self, reply: Reply, context: Context):
        receiver = context.get("receiver", "")
        msg = context.get("msg")
        context_token = self._get_context_token(receiver, msg)

        if not context_token:
            # Raise rather than return: a scheduled push routes through this same
            # send(), and the scheduler treats a silent return as "delivered" and
            # deletes a one-time task. Without a context_token the message cannot
            # go out, so surface it as a failure the caller can defer/retry on.
            raise RuntimeError(
                f"[Weixin] No context_token for receiver={receiver}, cannot send"
            )

        # A media reply can carry an accompanying message (the agent's summary of
        # the file it just sent). ilink has no caption field, so it goes out as a
        # separate bubble first. Image replies are skipped: chat_channel already
        # splits their text off before we get here, and doing it again would
        # duplicate the bubble.
        text_content = getattr(reply, "text_content", "") or ""
        if text_content and reply.type not in (ReplyType.TEXT, ReplyType.IMAGE_URL, ReplyType.IMAGE):
            self._send_text(text_content, receiver, context_token)
            time.sleep(0.3)

        if reply.type == ReplyType.TEXT:
            self._send_text(reply.content, receiver, context_token)
        elif reply.type in (ReplyType.IMAGE_URL, ReplyType.IMAGE):
            self._send_image(reply.content, receiver, context_token)
        elif reply.type == ReplyType.FILE:
            if getattr(reply, "file_type", "") == "video":
                self._send_video(reply.content, receiver, context_token)
            else:
                self._send_file(reply.content, receiver, context_token,
                                file_name=getattr(reply, "file_name", ""))
        elif reply.type in (ReplyType.VIDEO, ReplyType.VIDEO_URL):
            self._send_video(reply.content, receiver, context_token)
        elif reply.type == ReplyType.VOICE:
            # ilink has no outbound voice item; deliver TTS as a file attachment.
            self._send_file(reply.content, receiver, context_token)
        else:
            logger.warning(f"[Weixin] Unsupported reply type: {reply.type}, fallback to text")
            self._send_text(str(reply.content), receiver, context_token)

    def _get_context_token(self, receiver: str, msg=None) -> str:
        """Get the context_token for a receiver, required for all sends."""
        if msg and hasattr(msg, "context_token") and msg.context_token:
            return msg.context_token
        return self._context_tokens.get(receiver, "")

    def _check_send_response(self, resp, receiver: str) -> None:
        """Inspect a send-API response; log failures and drop stale context_token on -14.

        ilink uses ret/errcode = -14 to signal that the session (and any
        cached context_token) is no longer valid. The plugin keeps running
        because the bot itself can re-login; we just need to forget the
        per-user token so the next push won't retry forever.

        Other non-zero codes (e.g. the user has not messaged the bot within
        the last 24h, or the send quota is used up) come back with HTTP 200,
        so they would otherwise pass silently.
        """
        if not isinstance(resp, dict):
            return
        ret = resp.get("ret")
        errcode = resp.get("errcode")
        if ret == -14 or errcode == -14:
            logger.error(
                f"[Weixin] Send returned -14 (session expired) for "
                f"receiver={receiver}; dropping cached context_token"
            )
            self._invalidate_context_token(receiver)
        elif ret or errcode:
            logger.error(
                f"[Weixin] Send failed for receiver={receiver}: ret={ret} "
                f"errcode={errcode} errmsg={resp.get('errmsg', '')}. The user may "
                f"need to send a message to the bot to re-open the 24h send window"
            )

    def _send_text(self, text: str, receiver: str, context_token: str):
        if len(text) <= TEXT_CHUNK_LIMIT:
            try:
                resp = self.api.send_text(receiver, text, context_token)
                self._check_send_response(resp, receiver)
                logger.debug(f"[Weixin] Text sent to {receiver}, len={len(text)}")
            except Exception as e:
                logger.error(f"[Weixin] Failed to send text: {e}")
            return

        chunks = self._split_text(text, TEXT_CHUNK_LIMIT)
        for i, chunk in enumerate(chunks):
            try:
                resp = self.api.send_text(receiver, chunk, context_token)
                self._check_send_response(resp, receiver)
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
        local_path, downloaded = self._resolve_media(img_path_or_url)
        if not local_path:
            self._send_text("[Image send failed: file not found]", receiver, context_token)
            return
        try:
            result = upload_media_to_cdn(self.api, local_path, receiver, media_type=1)
            resp = self.api.send_image_item(
                to=receiver,
                context_token=context_token,
                encrypt_query_param=result["encrypt_query_param"],
                aes_key_b64=result["aes_key_b64"],
                ciphertext_size=result["ciphertext_size"],
            )
            self._check_send_response(resp, receiver)
            logger.info(f"[Weixin] Image sent to {receiver}")
        except Exception as e:
            logger.error(f"[Weixin] Image send failed: {e}")
            self._send_text("[Image send failed]", receiver, context_token)
        finally:
            if downloaded:
                remove_download(local_path)

    def _send_file(self, file_path_or_url: str, receiver: str, context_token: str,
                   file_name: str = ""):
        local_path, downloaded = self._resolve_media(file_path_or_url)
        if not local_path:
            self._send_text("[File send failed: file not found]", receiver, context_token)
            return
        try:
            result = upload_media_to_cdn(self.api, local_path, receiver, media_type=3)
            resp = self.api.send_file_item(
                to=receiver,
                context_token=context_token,
                encrypt_query_param=result["encrypt_query_param"],
                aes_key_b64=result["aes_key_b64"],
                file_name=file_name or os.path.basename(local_path),
                file_size=result["raw_size"],
            )
            self._check_send_response(resp, receiver)
            logger.info(f"[Weixin] File sent to {receiver}")
        except Exception as e:
            logger.error(f"[Weixin] File send failed: {e}")
            self._send_text("[File send failed]", receiver, context_token)
        finally:
            if downloaded:
                remove_download(local_path)

    def _send_video(self, video_path_or_url: str, receiver: str, context_token: str):
        local_path, downloaded = self._resolve_media(video_path_or_url)
        if not local_path:
            self._send_text("[Video send failed: file not found]", receiver, context_token)
            return
        try:
            result = upload_media_to_cdn(self.api, local_path, receiver, media_type=2)
            resp = self.api.send_video_item(
                to=receiver,
                context_token=context_token,
                encrypt_query_param=result["encrypt_query_param"],
                aes_key_b64=result["aes_key_b64"],
                ciphertext_size=result["ciphertext_size"],
            )
            self._check_send_response(resp, receiver)
            logger.info(f"[Weixin] Video sent to {receiver}")
        except Exception as e:
            logger.error(f"[Weixin] Video send failed: {e}")
            self._send_text("[Video send failed]", receiver, context_token)
        finally:
            if downloaded:
                remove_download(local_path)

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
                resp = _open_media_response(local_path)
                ext = _guess_download_ext(local_path, resp.headers)
                tmp_path = state_dir.tmp_file("wx_media", ext)
                save_response(resp, tmp_path, MAX_FILE_BYTES,
                              max_seconds=_MAX_REMOTE_MEDIA_SECONDS)
                return tmp_path
            except Exception as e:
                logger.error(f"[Weixin] Failed to download media: {e}")
                return ""

        if os.path.exists(local_path):
            return local_path

        logger.warning(f"[Weixin] Media file not found: {local_path}")
        return ""

    @classmethod
    def _resolve_media(cls, path_or_url: str) -> Tuple[str, bool]:
        """Like :meth:`_resolve_media_path`, plus whether the file was downloaded here."""
        downloaded = bool(path_or_url) and path_or_url.startswith(
            ("http://", "https://"))
        local_path = cls._resolve_media_path(path_or_url)
        return local_path, bool(local_path) and downloaded
