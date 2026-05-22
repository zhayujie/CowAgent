"""
Weixin ChatMessage implementation.

Parses WeixinMessage from the getUpdates API into the unified ChatMessage format.
"""

import os
import uuid

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from channel.weixin.weixin_api import download_media_from_cdn, CDN_BASE_URL
from common.log import logger
from common.utils import expand_path
from config import conf


# MessageItemType constants from the Weixin protocol
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5


def _get_tmp_dir() -> str:
    ws_root = expand_path(conf().get("agent_workspace", "~/cow"))
    tmp_dir = os.path.join(ws_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


class WeixinMessage(ChatMessage):
    """Message wrapper for Weixin channel."""

    def __init__(self, msg: dict, cdn_base_url: str = CDN_BASE_URL):
        super().__init__(msg)

        self.msg_id = str(msg.get("message_id", msg.get("seq", uuid.uuid4().hex[:8])))
        self.create_time = msg.get("create_time_ms", 0)
        self.context_token = msg.get("context_token", "")
        self.is_group = False  # Weixin plugin only supports direct chat
        self.is_at = False

        from_user_id = msg.get("from_user_id", "")
        to_user_id = msg.get("to_user_id", "")

        self.from_user_id = from_user_id
        self.from_user_nickname = from_user_id
        self.to_user_id = to_user_id
        self.to_user_nickname = to_user_id
        self.other_user_id = from_user_id
        self.other_user_nickname = from_user_id
        self.actual_user_id = from_user_id
        self.actual_user_nickname = from_user_id

        item_list = msg.get("item_list", [])

        # Parse items: find text and media
        text_body = ""
        media_item = None
        media_type = None
        ref_text = ""

        for item in item_list:
            itype = item.get("type", 0)

            if itype == ITEM_TEXT:
                text_item = item.get("text_item", {})
                text_body = text_item.get("text", "")

                ref = item.get("ref_msg")
                if ref:
                    ref_title = ref.get("title", "")
                    ref_mi = ref.get("message_item", {})
                    ref_body = ""
                    if ref_mi.get("type") == ITEM_TEXT:
                        ref_body = ref_mi.get("text_item", {}).get("text", "")
                    if ref_title or ref_body:
                        parts = [p for p in [ref_title, ref_body] if p]
                        ref_text = f"[引用: {' | '.join(parts)}]\n"
                    # If ref is a media item, treat it as the media to download
                    if ref_mi.get("type") in (ITEM_IMAGE, ITEM_VIDEO, ITEM_FILE):
                        media_item = ref_mi
                        media_type = ref_mi.get("type")

            elif itype == ITEM_VOICE:
                voice_item = item.get("voice_item", {})
                voice_text = voice_item.get("text", "")
                if voice_text:
                    text_body = voice_text
                else:
                    # Voice without transcription - download the audio
                    media_item = item
                    media_type = ITEM_VOICE

            elif itype in (ITEM_IMAGE, ITEM_VIDEO, ITEM_FILE):
                if not media_item:
                    media_item = item
                    media_type = itype

        # Determine ctype and content
        if media_item and not text_body:
            self._setup_media(media_item, media_type, cdn_base_url)
        elif media_item and text_body:
            # Text + media: download media, attach as file ref in text
            self.ctype = ContextType.TEXT
            media_path = self._download_media(media_item, media_type, cdn_base_url)
            if media_path:
                if media_type == ITEM_IMAGE:
                    text_body += f"\n[图片: {media_path}]"
                elif media_type == ITEM_VIDEO:
                    text_body += f"\n[视频: {media_path}]"
                else:
                    text_body += f"\n[文件: {media_path}]"
            self.content = ref_text + text_body
        else:
            self.ctype = ContextType.TEXT
            self.content = ref_text + text_body

    def _setup_media(self, item: dict, media_type: int, cdn_base_url: str):
        """Set up message as a media type, with lazy download via _prepare_fn."""
        if media_type == ITEM_IMAGE:
            self.ctype = ContextType.IMAGE
            image_path = self._download_media(item, ITEM_IMAGE, cdn_base_url)
            if image_path:
                self.content = image_path
                self.image_path = image_path
            else:
                self.ctype = ContextType.TEXT
                self.content = "[Image download failed]"

        elif media_type == ITEM_VIDEO:
            self.ctype = ContextType.FILE
            save_path = os.path.join(_get_tmp_dir(), f"wx_{self.msg_id}.mp4")
            self.content = save_path

            def _download():
                path = self._download_media(item, ITEM_VIDEO, cdn_base_url)
                if path:
                    self.content = path
            self._prepare_fn = _download

        elif media_type == ITEM_FILE:
            self.ctype = ContextType.FILE
            file_name = item.get("file_item", {}).get("file_name", f"wx_{self.msg_id}")
            save_path = os.path.join(_get_tmp_dir(), file_name)
            self.content = save_path

            def _download():
                path = self._download_media(item, ITEM_FILE, cdn_base_url)
                if path:
                    self.content = path
            self._prepare_fn = _download

        elif media_type == ITEM_VOICE:
            self.ctype = ContextType.VOICE
            save_path = os.path.join(_get_tmp_dir(), f"wx_{self.msg_id}.silk")
            self.content = save_path

            def _download():
                path = self._download_media(item, ITEM_VOICE, cdn_base_url)
                if path:
                    self.content = path
            self._prepare_fn = _download

    def _download_media(self, item: dict, media_type: int, cdn_base_url: str) -> str:
        """Download media from CDN, returns local file path or empty string."""
        type_key_map = {
            ITEM_IMAGE: "image_item",
            ITEM_VIDEO: "video_item",
            ITEM_FILE: "file_item",
            ITEM_VOICE: "voice_item",
        }
        key = type_key_map.get(media_type, "")
        info = item.get(key, {})
        media = info.get("media", {})

        encrypt_param = media.get("encrypt_query_param", "")
        # aes_key can be in image_item.aeskey (hex) or media.aes_key (b64)
        aes_key = info.get("aeskey", "") or media.get("aes_key", "")

        if not encrypt_param or not aes_key:
            logger.warning(f"[Weixin] Missing CDN params for media download (type={media_type})")
            return ""

        if media_type == ITEM_FILE:
            original_name = info.get("file_name", "")
            if original_name:
                save_path = os.path.join(_get_tmp_dir(), original_name)
            else:
                save_path = os.path.join(_get_tmp_dir(), f"wx_{self.msg_id}.bin")
        else:
            ext_map = {ITEM_IMAGE: ".jpg", ITEM_VIDEO: ".mp4", ITEM_VOICE: ".silk"}
            ext = ext_map.get(media_type, "")
            save_path = os.path.join(_get_tmp_dir(), f"wx_{self.msg_id}{ext}")

        try:
            download_media_from_cdn(cdn_base_url, encrypt_param, aes_key, save_path)
            logger.info(f"[Weixin] Media downloaded: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"[Weixin] Media download failed: {e}")
            return ""
