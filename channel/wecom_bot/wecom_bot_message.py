import os
import re
import base64
import requests

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common.utils import expand_path
from config import conf
from Crypto.Cipher import AES


MAGIC_SIGNATURES = [
    (b"%PDF", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"RIFF", ".webp"),  # RIFF....WEBP, further checked below
    (b"PK\x03\x04", ".zip"),  # zip / docx / xlsx / pptx
    (b"\x1f\x8b", ".gz"),
    (b"Rar!\x1a\x07", ".rar"),
    (b"7z\xbc\xaf\x27\x1c", ".7z"),
    (b"\x00\x00\x00", ".mp4"),  # ftyp box, further checked below
    (b"#!AMR", ".amr"),
]

OFFICE_ZIP_MARKERS = {
    b"word/": ".docx",
    b"xl/": ".xlsx",
    b"ppt/": ".pptx",
}


def _guess_ext_from_bytes(data: bytes) -> str:
    """Guess file extension from file content magic bytes."""
    if not data or len(data) < 8:
        return ""
    for sig, ext in MAGIC_SIGNATURES:
        if data[:len(sig)] == sig:
            if ext == ".webp" and data[8:12] != b"WEBP":
                continue
            if ext == ".mp4":
                if b"ftyp" not in data[4:12]:
                    continue
            if ext == ".zip":
                for marker, office_ext in OFFICE_ZIP_MARKERS.items():
                    if marker in data[:2000]:
                        return office_ext
                return ".zip"
            return ext
    return ""


def _decrypt_media(url: str, aeskey: str) -> bytes:
    """
    Download and decrypt AES-256-CBC encrypted media from wecom bot.
    Returns decrypted bytes.
    """
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    encrypted = resp.content

    key = base64.b64decode(aeskey + "=" * (-len(aeskey) % 4))
    if len(key) != 32:
        raise ValueError(f"Invalid AES key length: {len(key)}, expected 32")

    iv = key[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted)

    pad_len = decrypted[-1]
    if pad_len > 32:
        raise ValueError(f"Invalid PKCS7 padding length: {pad_len}")
    return decrypted[:-pad_len]


def _get_tmp_dir() -> str:
    """Return the workspace tmp directory (absolute path), creating it if needed."""
    ws_root = expand_path(conf().get("agent_workspace", "~/cow"))
    tmp_dir = os.path.join(ws_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


class WecomBotMessage(ChatMessage):
    """Message wrapper for wecom bot (websocket long-connection mode)."""

    def __init__(self, msg_body: dict, is_group: bool = False):
        super().__init__(msg_body)
        self.msg_id = msg_body.get("msgid")
        self.create_time = msg_body.get("create_time")
        self.is_group = is_group

        msg_type = msg_body.get("msgtype")
        from_userid = msg_body.get("from", {}).get("userid", "")
        chat_id = msg_body.get("chatid", "")
        bot_id = msg_body.get("aibotid", "")

        if msg_type == "text":
            self.ctype = ContextType.TEXT
            content = msg_body.get("text", {}).get("content", "")
            if is_group:
                content = re.sub(r"@\S+\s*", "", content).strip()
            self.content = content

        elif msg_type == "voice":
            self.ctype = ContextType.TEXT
            self.content = msg_body.get("voice", {}).get("content", "")

        elif msg_type == "image":
            self.ctype = ContextType.IMAGE
            image_info = msg_body.get("image", {})
            image_url = image_info.get("url", "")
            aeskey = image_info.get("aeskey", "")
            tmp_dir = _get_tmp_dir()
            image_path = os.path.join(tmp_dir, f"wecom_{self.msg_id}.png")

            try:
                data = _decrypt_media(image_url, aeskey)
                with open(image_path, "wb") as f:
                    f.write(data)
                self.content = image_path
                self.image_path = image_path
                logger.info(f"[WecomBot] Image downloaded: {image_path}")
            except Exception as e:
                logger.error(f"[WecomBot] Failed to download image: {e}")
                self.content = "[Image download failed]"
                self.image_path = None

        elif msg_type == "mixed":
            self.ctype = ContextType.TEXT
            text_parts = []
            image_paths = []
            mixed_items = msg_body.get("mixed", {}).get("msg_item", [])
            tmp_dir = _get_tmp_dir()

            for idx, item in enumerate(mixed_items):
                item_type = item.get("msgtype")
                if item_type == "text":
                    txt = item.get("text", {}).get("content", "")
                    if is_group:
                        txt = re.sub(r"@\S+\s*", "", txt).strip()
                    if txt:
                        text_parts.append(txt)
                elif item_type == "image":
                    img_info = item.get("image", {})
                    img_url = img_info.get("url", "")
                    img_aeskey = img_info.get("aeskey", "")
                    img_path = os.path.join(tmp_dir, f"wecom_{self.msg_id}_{idx}.png")
                    try:
                        img_data = _decrypt_media(img_url, img_aeskey)
                        with open(img_path, "wb") as f:
                            f.write(img_data)
                        image_paths.append(img_path)
                    except Exception as e:
                        logger.error(f"[WecomBot] Failed to download mixed image: {e}")

            content_parts = text_parts[:]
            for p in image_paths:
                content_parts.append(f"[图片: {p}]")
            self.content = "\n".join(content_parts) if content_parts else "[Mixed message]"

        elif msg_type == "file":
            self.ctype = ContextType.FILE
            file_info = msg_body.get("file", {})
            file_url = file_info.get("url", "")
            aeskey = file_info.get("aeskey", "")
            tmp_dir = _get_tmp_dir()
            base_path = os.path.join(tmp_dir, f"wecom_{self.msg_id}")
            self.content = base_path

            def _download_file():
                try:
                    data = _decrypt_media(file_url, aeskey)
                    ext = _guess_ext_from_bytes(data)
                    final_path = base_path + ext
                    with open(final_path, "wb") as f:
                        f.write(data)
                    self.content = final_path
                    logger.info(f"[WecomBot] File downloaded: {final_path}")
                except Exception as e:
                    logger.error(f"[WecomBot] Failed to download file: {e}")
            self._prepare_fn = _download_file

        elif msg_type == "video":
            self.ctype = ContextType.FILE
            video_info = msg_body.get("video", {})
            video_url = video_info.get("url", "")
            aeskey = video_info.get("aeskey", "")
            tmp_dir = _get_tmp_dir()
            self.content = os.path.join(tmp_dir, f"wecom_{self.msg_id}.mp4")

            def _download_video():
                try:
                    data = _decrypt_media(video_url, aeskey)
                    with open(self.content, "wb") as f:
                        f.write(data)
                    logger.info(f"[WecomBot] Video downloaded: {self.content}")
                except Exception as e:
                    logger.error(f"[WecomBot] Failed to download video: {e}")
            self._prepare_fn = _download_video

        else:
            raise NotImplementedError(f"Unsupported message type: {msg_type}")

        self.from_user_id = from_userid
        self.to_user_id = bot_id
        if is_group:
            self.other_user_id = chat_id
            self.actual_user_id = from_userid
            self.actual_user_nickname = from_userid
        else:
            self.other_user_id = from_userid
            self.actual_user_id = from_userid
