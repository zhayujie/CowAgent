# -*- coding=utf-8 -*-
"""
Adapter that turns a single `sync_msg` item from WeCom customer-service
into a CoW `ChatMessage` object.
"""
import os
import re

from wechatpy.enterprise import WeChatClient

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common.utils import expand_path
from config import conf


def _get_tmp_dir() -> str:
    """Save under agent_workspace/tmp/ so agent tools (e.g. `read`) can
    resolve a relative path like `tmp/xxx.pdf` against their own
    workspace root. Mirrors the convention used by weixin / wecom_bot.
    """
    ws_root = expand_path(conf().get("agent_workspace", "~/cow"))
    tmp_dir = os.path.join(ws_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


def _extract_filename(content_disposition: str) -> str:
    """Best-effort parse of `filename` / `filename*` from a Content-Disposition
    header. Returns '' when nothing usable is found."""
    if not content_disposition:
        return ""
    # RFC 5987 form: filename*=UTF-8''xxx
    m = re.search(r"filename\*=(?:[^'\"]*'[^']*'\s*)?([^;]+)", content_disposition)
    if m:
        try:
            from urllib.parse import unquote
            return unquote(m.group(1).strip().strip('"'))
        except Exception:
            return m.group(1).strip().strip('"')
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition)
    return m.group(1).strip() if m else ""


class WechatKfMessage(ChatMessage):
    """
    msg structure (from cgi-bin/kf/sync_msg):
        {
          "msgid": "...",
          "send_time": 1700000000,
          "origin": 3,
          "msgtype": "text" | "image" | "voice" | ...,
          "open_kfid": "wkxxxx",
          "external_userid": "wmxxxx",
          "text": {"content": "..."},
          "image": {"media_id": "..."},
          "voice": {"media_id": "..."},
          ...
        }
    """

    def __init__(self, msg: dict, client: WeChatClient = None, is_group: bool = False):
        # NOTE: skip parent constructor because it expects a wechatpy parsed
        # message object, while here we receive a raw dict from sync_msg.
        super().__init__(msg)
        self.is_group = is_group
        self.msg_id = msg.get("msgid")
        self.create_time = msg.get("send_time")
        self.origin = msg.get("origin")
        self.msgtype = msg.get("msgtype")
        self.open_kfid = msg.get("open_kfid")
        self.external_userid = msg.get("external_userid")

        if self.msgtype == "text":
            self.ctype = ContextType.TEXT
            self.content = msg.get("text", {}).get("content", "")
        elif self.msgtype == "image":
            self.ctype = ContextType.IMAGE
            media_id = msg.get("image", {}).get("media_id", "")
            self.content = os.path.join(_get_tmp_dir(), media_id + ".jpg")

            def download_image():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechat_kf] Failed to download image, {response.content}")

            self._prepare_fn = download_image
        elif self.msgtype == "voice":
            self.ctype = ContextType.VOICE
            media_id = msg.get("voice", {}).get("media_id", "")
            # WeCom returns amr by default; downstream voice pipeline will convert.
            self.content = os.path.join(_get_tmp_dir(), media_id + ".amr")

            def download_voice():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechat_kf] Failed to download voice, {response.content}")

            self._prepare_fn = download_voice
        elif self.msgtype == "file":
            self.ctype = ContextType.FILE
            media_id = msg.get("file", {}).get("media_id", "")
            # Provisional path; rewritten in download_file() once we have
            # the original filename from Content-Disposition.
            self.content = os.path.join(_get_tmp_dir(), media_id)

            def download_file():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    filename = _extract_filename(
                        response.headers.get("Content-Disposition", "")
                    ) or media_id
                    self.content = os.path.join(_get_tmp_dir(), filename)
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechat_kf] Failed to download file, {response.content}")

            self._prepare_fn = download_file
        else:
            raise NotImplementedError(
                f"[wechat_kf] Unsupported message type: {self.msgtype}"
            )

        self.from_user_id = self.external_userid
        self.to_user_id = self.open_kfid
        self.other_user_id = self.external_userid
