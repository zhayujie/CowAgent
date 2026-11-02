from bridge.context import ContextType
from channel.chat_message import ChatMessage
from channel.chat_message import safe_filename
import json
import os
import re
import requests
from common.log import logger
from common import state_dir, utils
from common.media_download import MAX_FILE_BYTES, MAX_IMAGE_BYTES, download_to_file


def _download_resource(message_id, key, resource_type, access_token, path, max_bytes) -> bool:
    """Save one message resource (image / file / audio) to ``path``."""
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{key}"
    try:
        download_to_file(
            url, path, max_bytes, timeout=(5, 30),
            headers={"Authorization": "Bearer " + access_token},
            params={"type": resource_type},
        )
        return True
    except Exception as e:
        logger.error(f"[FeiShu] Failed to download {resource_type}, key={key}: {e}")
        return False


def _mention_labels(mentions, bot_mention_keys) -> dict:
    """What the agent reads in place of each mention key.

    A text message writes the n-th person it @-mentions, the bot included, as
    the key @_user_n; the event's "mentions" pairs each key with that person's
    name. A person reads as "@name" and the bot's own mention as nothing. A key
    that comes without a name is its own label, so its placeholder stays as it is.
    """
    labels = {}
    for mention in mentions or []:
        key = mention.get("key")
        if not key:
            continue
        if key in bot_mention_keys:
            labels[key] = ""
        else:
            labels[key] = "@" + mention["name"] if mention.get("name") else key
    return labels


def _name_mentions(text, labels) -> str:
    """Put each key's label in its place; the bot's key goes with the spaces after it.

    Only the keys of the message's own mentions are matched, the longest first:
    with twelve mentions @_user_12 is one key, and with fewer it is @_user_1
    followed by a 2 the sender typed.
    """
    if not labels:
        return text

    def replace(match):
        key, spaces = match.groups()
        return labels[key] + spaces if labels[key] else ""

    keys = "|".join(re.escape(key) for key in sorted(labels, key=len, reverse=True))
    return re.sub(f"({keys})( *)", replace, text)


class FeishuMessage(ChatMessage):
    # Message types __init__ can parse; anything else raises NotImplementedError.
    SUPPORTED_TYPES = ("text", "image", "post", "file", "audio")

    def __init__(self, event: dict, is_group=False, access_token=None, bot_mention_keys=()):
        super().__init__(event)
        msg = event.get("message")
        sender = event.get("sender")
        self.access_token = access_token
        self.msg_id = msg.get("message_id")
        self.create_time = msg.get("create_time")
        self.is_group = is_group
        self.quoted_content = ""
        msg_type = msg.get("message_type")
        # Who each mention key in a group message stands for; bot_mention_keys
        # are the bot's own. Direct messages are left as they are.
        mention_labels = _mention_labels(msg.get("mentions"), bot_mention_keys) if is_group else {}

        if msg_type == "text":
            self.ctype = ContextType.TEXT
            content = json.loads(msg.get('content'))
            self.content = content.get("text").strip()
        elif msg_type == "image":
            # 单张图片消息：下载并缓存，等待用户提问时一起发送
            self.ctype = ContextType.IMAGE
            content = json.loads(msg.get("content"))
            image_key = content.get("image_key")
            
            # 下载图片到工作空间临时目录
            tmp_dir = str(state_dir.tmp_dir())
            image_path = os.path.join(tmp_dir, f"{safe_filename(image_key) or 'image'}.png")
            if _download_resource(self.msg_id, image_key, "image", access_token, image_path, MAX_IMAGE_BYTES):
                logger.info(f"[FeiShu] Downloaded single image, key={image_key}, path={image_path}")
                self.content = image_path
                self.image_path = image_path  # 保存图片路径
            else:
                self.content = f"[图片下载失败: {image_key}]"
                self.image_path = None
        elif msg_type == "post":
            # 富文本消息，可能包含图片、文本、视频、文件等多种元素
            raw_content = json.loads(msg.get("content"))
            content = raw_content
            # Some payloads wrap the post body in a locale key, e.g. {"zh_cn": {...}}.
            if "content" not in content:
                localized = next((v for v in content.values() if isinstance(v, dict)), None)
                if localized:
                    content = localized

            title = content.get("title", "")
            content_list = content.get("content") or []

            logger.info(f"[FeiShu] Post message - title: '{title}', content_list length: {len(content_list)}")

            image_keys = []
            text_parts = []
            # Where the @-mentions sit in text_parts; they are not the post's own words
            mention_parts = set()
            # (file_key, file_name, file_type) for videos and file attachments
            file_items = []
            folder_names = []

            if title:
                text_parts.append(title)

            for block in content_list:
                logger.debug(f"[FeiShu] Processing block: {block}")
                # block 本身就是元素列表
                if not isinstance(block, list):
                    continue

                for element in block:
                    if not isinstance(element, dict):
                        continue
                    element_tag = element.get("tag")
                    logger.debug(f"[FeiShu] Element tag: {element_tag}, element: {element}")
                    if element_tag == "img":
                        image_key = element.get("image_key")
                        if image_key:
                            image_keys.append(image_key)
                    elif element_tag in ("text", "code_block"):
                        text_content = element.get("text", "")
                        if text_content:
                            text_parts.append(text_content)
                    elif element_tag == "a":
                        link_text = element.get("text", "")
                        href = element.get("href", "")
                        if link_text or href:
                            text_parts.append(f"{link_text} ({href})" if link_text and href else (link_text or href))
                    elif element_tag == "at":
                        # user_id is the mention key (@_user_n) here, not an id.
                        # The bot's own key and a key without a name are left out.
                        key = element.get("user_id")
                        label = mention_labels.get(key)
                        if label and label != key:
                            mention_parts.add(len(text_parts))
                            text_parts.append(label)
                    elif element_tag == "media":
                        file_key = element.get("file_key")
                        if file_key:
                            file_items.append((file_key, element.get("file_name") or "video.mp4", "video"))

            # A file sent together with a caption arrives as a post whose
            # attachments sit in a top-level "files" array next to "content".
            files = list(content.get("files") or [])
            if raw_content is not content:
                files += raw_content.get("files") or []
            for f in files:
                if not isinstance(f, dict) or not f.get("file_key"):
                    continue
                file_name = f.get("file_name") or "file"
                if f.get("is_folder"):
                    # Folders can only be opened in the client, not downloaded via API.
                    folder_names.append(file_name)
                else:
                    file_items.append((f["file_key"], file_name, "file"))

            logger.info(
                f"[FeiShu] Parsed - images: {len(image_keys)}, files: {len(file_items)}, "
                f"folders: {len(folder_names)}, text_parts: {text_parts}"
            )

            # 富文本消息统一作为文本消息处理
            self.ctype = ContextType.TEXT
            # The post's own words: @-mentions alone don't make a post of files
            # a question, so the channel still caches its files until one comes.
            self.post_text = "\n".join(p for i, p in enumerate(text_parts) if i not in mention_parts).strip()
            # (local_path, file_type) of every successfully downloaded attachment
            self.attachments = []
            tmp_dir = str(state_dir.tmp_dir())
            text = "\n".join(text_parts).strip()
            content_parts = [text] if text else []

            # Only successful downloads are recorded as paths; failed ones
            # keep a marker so the agent knows something was sent.
            self.image_paths = {}
            failed_images = []
            for image_key in dict.fromkeys(image_keys):
                image_path = os.path.join(tmp_dir, f"{safe_filename(image_key) or 'image'}.png")
                if _download_resource(self.msg_id, image_key, "image", access_token, image_path, MAX_IMAGE_BYTES):
                    self.image_paths[image_key] = image_path
                    self.attachments.append((image_path, "image"))
                    logger.info(f"[FeiShu] Image downloaded from post message, key={image_key}, path={image_path}")
                else:
                    failed_images.append(image_key)
            for image_path in self.image_paths.values():
                content_parts.append(f"[图片: {image_path}]")
            for image_key in failed_images:
                content_parts.append(f"[图片下载失败: {image_key}]")

            self.failed_files = []
            seen_file_keys = set()
            for file_key, file_name, file_type in file_items:
                if file_key in seen_file_keys:
                    continue
                seen_file_keys.add(file_key)
                suffix = utils.get_path_suffix(file_name)
                file_path = os.path.join(
                    tmp_dir, f"{safe_filename(file_key) or file_type}" + (f".{suffix}" if suffix else "")
                )
                label = "视频" if file_type == "video" else "文件"
                if _download_resource(self.msg_id, file_key, "file", access_token, file_path, MAX_FILE_BYTES):
                    self.attachments.append((file_path, file_type))
                    content_parts.append(f"[{label}: {file_path}]")
                    logger.info(f"[FeiShu] {file_type} downloaded from post message, key={file_key}, path={file_path}")
                else:
                    self.failed_files.append(file_name)
                    content_parts.append(f"[{label}下载失败: {file_name}]")
            for folder_name in folder_names:
                content_parts.append(f"[文件夹: {folder_name}]")

            self.has_file_attachments = bool(file_items)
            self.content = "\n".join(content_parts) if content_parts else "[富文本消息]"
            logger.info(f"[FeiShu] Received post message: {self.content}")
        elif msg_type == "file":
            self.ctype = ContextType.FILE
            content = json.loads(msg.get("content"))
            file_key = content.get("file_key")
            file_name = content.get("file_name")

            # 落到工作空间 tmp 下（绝对路径），与图片处理一致；
            # 否则相对路径 ./tmp 在 agent 工作区里 read 时会找不到。
            tmp_dir = str(state_dir.tmp_dir())
            self.content = os.path.join(
                tmp_dir, f"{safe_filename(file_key) or 'file'}.{utils.get_path_suffix(file_name)}"
            )

            def _download_file():
                _download_resource(self.msg_id, file_key, "file", access_token, self.content, MAX_FILE_BYTES)
            self._prepare_fn = _download_file
        elif msg_type == "audio":
            # 飞书用户发送的语音消息类型为 "audio"，文件为 opus 编码格式。
            # 映射为 ContextType.VOICE，交由 chat_channel 的语音转文字（STT）流程处理。
            # 文件通过 _prepare_fn 延迟下载，在 chat_channel 调用 cmsg.prepare() 时才执行。
            self.ctype = ContextType.VOICE
            content = json.loads(msg.get("content"))
            file_key = content.get("file_key")

            # 落到工作空间 tmp 下（绝对路径），保证语音 STT 流程可读到
            tmp_dir = str(state_dir.tmp_dir())
            self.content = os.path.join(tmp_dir, f"{safe_filename(file_key) or 'audio'}.opus")
            logger.info(f"[FeiShu] audio message: file_key={file_key}, save_path={self.content}")

            def _download_audio():
                logger.info(f"[FeiShu] downloading audio: file_key={file_key}, msg_id={self.msg_id}")
                if _download_resource(self.msg_id, file_key, "file", access_token, self.content, MAX_FILE_BYTES):
                    logger.info(f"[FeiShu] audio saved to: {self.content}")
            self._prepare_fn = _download_audio
        else:
            raise NotImplementedError("Unsupported message type: Type:{} ".format(msg_type))

        if self.ctype == ContextType.TEXT:
            self.quoted_content = self._fetch_quoted_content(msg.get("parent_id"))

        self.from_user_id = sender.get("sender_id").get("open_id")
        self.to_user_id = event.get("app_id")
        if is_group:
            # 群聊
            self.other_user_id = msg.get("chat_id")
            self.actual_user_id = self.from_user_id
            self.content = _name_mentions(self.content, mention_labels).strip()
            self.actual_user_nickname = ""
        else:
            # 私聊
            self.other_user_id = self.from_user_id
            self.actual_user_id = self.from_user_id

    def content_with_quote(self) -> str:
        """Return user text with optional quoted-message context for the agent."""
        if not self.quoted_content:
            return self.content
        return (
            "[Quoted message]\n{}\n[/Quoted message]\n\n{}".format(
                self.quoted_content,
                self.content,
            )
        )

    def _fetch_quoted_content(self, parent_id: str) -> str:
        """Fetch one parent message, degrading to an empty quote on failure."""
        if not parent_id or not self.access_token:
            return ""

        url = "https://open.feishu.cn/open-apis/im/v1/messages/{}".format(parent_id)
        headers = {"Authorization": "Bearer " + self.access_token}
        try:
            response = requests.get(
                url=url,
                headers=headers,
                params={"card_msg_content_type": "raw_card_content"},
                timeout=(5, 10),
            )
            if response.status_code != 200:
                logger.warning(
                    "[FeiShu] quoted message fetch failed, parent_id=%s, status=%s",
                    parent_id,
                    response.status_code,
                )
                return ""
            body = response.json()
            items = (body.get("data") or {}).get("items") or []
            if body.get("code") != 0 or not items:
                return ""
            return self._extract_quoted_text(items[0])
        except Exception as exc:
            logger.warning(
                "[FeiShu] quoted message fetch error, parent_id=%s: %s",
                parent_id,
                exc,
            )
            return ""

    @staticmethod
    def _extract_quoted_text(item: dict) -> str:
        msg_type = item.get("msg_type")
        raw_content = (item.get("body") or {}).get("content") or ""
        try:
            content = json.loads(raw_content)
        except (TypeError, ValueError):
            return ""

        if msg_type == "text":
            return str(content.get("text") or "").strip()
        if msg_type == "post":
            # Some message-history payloads wrap post content in a locale key.
            if "content" not in content:
                localized = next(
                    (value for value in content.values() if isinstance(value, dict)),
                    None,
                )
                if localized:
                    content = localized

            parts = []
            title = str(content.get("title") or "").strip()
            if title:
                parts.append(title)
            for block in content.get("content") or []:
                if not isinstance(block, list):
                    continue
                for element in block:
                    if not isinstance(element, dict):
                        continue
                    tag = element.get("tag")
                    text = str(element.get("text") or "").strip()
                    if tag == "text" and text:
                        parts.append(text)
                    elif tag == "a" and text:
                        href = str(element.get("href") or "").strip()
                        parts.append("{} ({})".format(text, href) if href else text)
                    elif tag == "img":
                        parts.append("[Image]")
            return "\n".join(parts).strip()
        if msg_type == "image":
            return "[Image]"
        if msg_type == "file":
            return "[File: {}]".format(content.get("file_name") or "file")
        if msg_type == "audio":
            return "[Audio]"
        if msg_type == "media":
            return "[Video: {}]".format(content.get("file_name") or "video")
        return ""
