import os

from bridge.context import ContextType
from channel.chat_message import ChatMessage, safe_filename
from common.log import logger
from common import state_dir
from common.media_download import MAX_FILE_BYTES, download_to_file


def _get_tmp_dir() -> str:
    """Return the workspace tmp directory (absolute path), creating it if needed."""
    return str(state_dir.tmp_dir())


def _normalize_url(url: str) -> str:
    """QQ attachment URLs sometimes come back without a scheme."""
    if url and not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def _attachment_kind(content_type: str) -> str:
    """Classify a QQ attachment by its content_type into image/video/voice/file.

    Per the QQ Bot docs, content_type is a MIME type for media
    (image/jpeg, image/png, image/gif, video/mp4) or a bare tag for the
    rest (``voice`` for voice messages, ``file`` for group files).
    """
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/") or ct == "video":
        return "video"
    if ct.startswith("audio/") or ct in ("voice", "silk"):
        return "voice"
    return "file"


def _download_attachment(att: dict, msg_id: str, idx: int) -> str:
    """Download one non-image attachment to the tmp dir, returning its local
    path (or '' on failure). The extension is taken from the server filename
    when present so the agent's file tools can infer the type."""
    url = _normalize_url(att.get("url", ""))
    if not url:
        return ""
    tmp_dir = _get_tmp_dir()
    fname = safe_filename(att.get("filename", ""))
    if not fname:
        fname = f"qq_{msg_id}_{idx}"
    # Keep filenames unique per message so two attachments never clobber.
    local_path = os.path.join(tmp_dir, f"qq_{msg_id}_{idx}_{fname}")
    try:
        download_to_file(url, local_path, MAX_FILE_BYTES, timeout=60)
        logger.info(f"[QQ] Attachment downloaded: {local_path}")
        return local_path
    except Exception as e:
        logger.error(f"[QQ] Failed to download attachment: {e}")
        return ""


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

        attachments = event_data.get("attachments", []) or []
        # A standalone file / image is cached by the channel and attached to the
        # user's next message; hold its local path here for that flow.
        self.image_path = None
        self.file_path = None
        self.file_type = None
        # QQ's own ASR transcript for a voice attachment (asr_refer_text);
        # empty for non-voice messages or when the server omits the field.
        self.asr_text = ""
        # Traceability marker: set to VOICE when a voice message is promoted
        # to TEXT via the official transcript, so downstream (plugins, logs)
        # can still tell the message originated as voice.
        self.origin_ctype = None

        images = [a for a in attachments if _attachment_kind(a.get("content_type", "")) == "image"]
        non_images = [a for a in attachments if _attachment_kind(a.get("content_type", "")) != "image"]

        if attachments and not content and len(attachments) == 1 and images:
            # Single image, no caption: keep the legacy IMAGE flow so the channel
            # caches it and the next text message picks it up.
            self.ctype = ContextType.IMAGE
            image_path = _download_attachment(images[0], self.msg_id, 0)
            if image_path:
                self.content = image_path
                self.image_path = image_path
            else:
                self.content = "[Image download failed]"
        elif attachments and not content and len(attachments) == 1 and non_images:
            # Single file / video / voice, no caption. A voice message that
            # carries QQ's official ASR transcript goes straight through as
            # TEXT so it triggers an immediate reply; everything else keeps
            # the legacy FILE cache flow (answered with the user's next
            # text message).
            att = non_images[0]
            kind = _attachment_kind(att.get("content_type", ""))
            asr = str(att.get("asr_refer_text") or "").strip() if kind == "voice" else ""
            if kind == "voice" and asr:
                # Official transcript available: reply now with the recognized
                # text instead of caching the audio and waiting for a
                # follow-up message.
                local_path = _download_attachment(att, self.msg_id, 0)
                self.origin_ctype = ContextType.VOICE
                self.ctype = ContextType.TEXT
                self.content = asr
                self.file_path = local_path or None
                self.file_type = "voice"
                self.asr_text = asr
                logger.info(
                    "[QQ] VOICE->TEXT via official ASR | "
                    f"msg_id={self.msg_id} | event={event_type} | "
                    f"asr_refer_text({len(asr)} chars)=\"{asr}\" | "
                    f"audio_saved={local_path or 'DOWNLOAD_FAILED'} | "
                    "downstream sees TEXT (immediate reply), origin=VOICE"
                )
            else:
                # Plain file / video / voice without a transcript: keep the
                # FILE cache path so the user's next text message picks it up.
                self.ctype = ContextType.FILE
                self.file_type = kind
                local_path = _download_attachment(att, self.msg_id, 0)
                self.file_path = local_path
                if local_path:
                    self.content = local_path
                else:
                    self.content = f"[{kind} download failed]"
                if kind == "voice":
                    logger.info(
                        "[QQ] voice WITHOUT asr_refer_text -> FILE cache path | "
                        f"msg_id={self.msg_id} | audio_saved={local_path or 'DOWNLOAD_FAILED'} | "
                        "no reply until the next text message arrives"
                    )
        elif attachments:
            # Mixed message (caption + one or more attachments), or several
            # attachments at once: download everything and inline the local
            # paths as markers the agent can act on, mirroring the WeCom channel.
            self.ctype = ContextType.TEXT
            content_parts = [content] if content else []
            for idx, att in enumerate(attachments):
                kind = _attachment_kind(att.get("content_type", ""))
                asr = str(att.get("asr_refer_text") or "").strip()
                path = _download_attachment(att, self.msg_id, idx)
                if not path:
                    if kind == "voice" and asr:
                        content_parts.append(f"[语音转文字: {asr}]")
                    continue
                if kind == "image":
                    content_parts.append(f"[图片: {path}]")
                elif kind == "video":
                    content_parts.append(f"[视频: {path}]")
                elif kind == "voice":
                    if asr:
                        content_parts.append(f"[语音: {path}\nQQ官方转写: {asr}]")
                    else:
                        content_parts.append(f"[语音: {path}]")
                else:
                    content_parts.append(f"[文件: {path}]")
            self.content = "\n".join(content_parts) if content_parts else "[Attachment received]"
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

        origin_note = ""
        if self.origin_ctype == ContextType.VOICE:
            origin_note = ", origin=VOICE (VOICE->TEXT via official ASR)"
        logger.debug(f"[QQ] Message parsed: type={event_type}, ctype={self.ctype}{origin_note}, "
                     f"from={self.from_user_id}, content_len={len(self.content)}")
