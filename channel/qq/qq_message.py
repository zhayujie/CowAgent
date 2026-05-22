import os
import requests

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common.utils import expand_path
from config import conf


def _get_tmp_dir() -> str:
    """Return the workspace tmp directory (absolute path), creating it if needed."""
    ws_root = expand_path(conf().get("agent_workspace", "~/cow"))
    tmp_dir = os.path.join(ws_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


class QQMessage(ChatMessage):
    """Message wrapper for QQ Bot (websocket long-connection mode)."""

    def __init__(self, event_data: dict, event_type: str):
        super().__init__(event_data)
        self.msg_id = event_data.get("id", "")
        self.create_time = event_data.get("timestamp", "")
        self.is_group = event_type in ("GROUP_AT_MESSAGE_CREATE",)
        self.event_type = event_type

        author = event_data.get("author", {})
        from_user_id = author.get("member_openid", "") or author.get("id", "")
        group_openid = event_data.get("group_openid", "")

        content = event_data.get("content", "").strip()

        attachments = event_data.get("attachments", [])
        has_image = any(
            a.get("content_type", "").startswith("image/") for a in attachments
        ) if attachments else False

        if has_image and not content:
            self.ctype = ContextType.IMAGE
            img_attachment = next(
                a for a in attachments if a.get("content_type", "").startswith("image/")
            )
            img_url = img_attachment.get("url", "")
            if img_url and not img_url.startswith("http"):
                img_url = "https://" + img_url
            tmp_dir = _get_tmp_dir()
            image_path = os.path.join(tmp_dir, f"qq_{self.msg_id}.png")
            try:
                resp = requests.get(img_url, timeout=30)
                resp.raise_for_status()
                with open(image_path, "wb") as f:
                    f.write(resp.content)
                self.content = image_path
                self.image_path = image_path
                logger.info(f"[QQ] Image downloaded: {image_path}")
            except Exception as e:
                logger.error(f"[QQ] Failed to download image: {e}")
                self.content = "[Image download failed]"
                self.image_path = None
        elif has_image and content:
            self.ctype = ContextType.TEXT
            image_paths = []
            tmp_dir = _get_tmp_dir()
            for idx, att in enumerate(attachments):
                if not att.get("content_type", "").startswith("image/"):
                    continue
                img_url = att.get("url", "")
                if img_url and not img_url.startswith("http"):
                    img_url = "https://" + img_url
                img_path = os.path.join(tmp_dir, f"qq_{self.msg_id}_{idx}.png")
                try:
                    resp = requests.get(img_url, timeout=30)
                    resp.raise_for_status()
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    image_paths.append(img_path)
                except Exception as e:
                    logger.error(f"[QQ] Failed to download mixed image: {e}")
            content_parts = [content]
            for p in image_paths:
                content_parts.append(f"[图片: {p}]")
            self.content = "\n".join(content_parts)
        else:
            self.ctype = ContextType.TEXT
            self.content = content

        if event_type == "GROUP_AT_MESSAGE_CREATE":
            self.from_user_id = from_user_id
            self.to_user_id = ""
            self.other_user_id = group_openid
            self.actual_user_id = from_user_id
            self.actual_user_nickname = from_user_id

        elif event_type == "C2C_MESSAGE_CREATE":
            user_openid = author.get("user_openid", "") or from_user_id
            self.from_user_id = user_openid
            self.to_user_id = ""
            self.other_user_id = user_openid
            self.actual_user_id = user_openid

        elif event_type == "AT_MESSAGE_CREATE":
            self.from_user_id = from_user_id
            self.to_user_id = ""
            channel_id = event_data.get("channel_id", "")
            self.other_user_id = channel_id
            self.actual_user_id = from_user_id
            self.actual_user_nickname = author.get("username", from_user_id)

        elif event_type == "DIRECT_MESSAGE_CREATE":
            self.from_user_id = from_user_id
            self.to_user_id = ""
            guild_id = event_data.get("guild_id", "")
            self.other_user_id = f"dm_{guild_id}_{from_user_id}"
            self.actual_user_id = from_user_id
            self.actual_user_nickname = author.get("username", from_user_id)

        else:
            raise NotImplementedError(f"Unsupported QQ event type: {event_type}")

        logger.debug(f"[QQ] Message parsed: type={event_type}, ctype={self.ctype}, "
                     f"from={self.from_user_id}, content_len={len(self.content)}")
