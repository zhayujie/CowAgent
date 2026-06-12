"""
Telegram channel via Bot API (long polling mode).

Features:
- Single chat & group chat (text / photo / voice / video / document)
- Group trigger: @mention or reply-to-bot (configurable)
- /cancel fast-path matches Web channel behaviour
- Auto-register bot commands menu on startup (mirrors Web slash menu)
- Optional HTTP/SOCKS5 proxy support for restricted networks

Implementation note:
    python-telegram-bot is async-first. We run the bot inside a dedicated
    thread with its own asyncio loop so the rest of cow (which is sync)
    stays untouched. Inbound updates are dispatched onto cow's existing
    sync ChatChannel.produce() pipeline; outbound send() schedules
    coroutines back onto that loop via asyncio.run_coroutine_threadsafe.
"""

import asyncio
import os
import re
import threading

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.telegram.telegram_message import TelegramMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from config import conf

# Bot command menu, aligned with Web slash commands.
# Top-level commands only; sub-commands are entered with a space (e.g. "/skill list").
TELEGRAM_BOT_COMMANDS = [
    ("help", "Show command help"),
    ("status", "Show running status"),
    ("context", "View/clear conversation context (sub: clear)"),
    ("skill", "Manage skills (list/search/install/...)"),
    ("memory", "Manage memory (sub: dream)"),
    ("knowledge", "Manage knowledge base (list/on/off)"),
    ("config", "Show current config"),
    ("cancel", "Cancel running agent task"),
    ("logs", "Show recent logs"),
    ("version", "Show version"),
]


@singleton
class TelegramChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.bot_token = ""
        self.bot_username = ""  # used for @-mention matching
        self._bot = None
        self._application = None
        self._loop = None
        self._loop_thread = None
        self._stop_event = threading.Event()
        # Idempotent dedup; TG occasionally redelivers the same update on flaky networks
        self._received_msgs = ExpiredDict(60 * 60 * 1)

        # Disable group whitelist / prefix checks (we handle triggering ourselves
        # in _should_reply_in_group), aligned with feishu / wecom_bot channels.
        conf()["group_name_white_list"] = ["ALL_GROUP"]
        conf()["single_chat_prefix"] = [""]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self):
        self.bot_token = conf().get("telegram_token", "")
        if not self.bot_token:
            err = "[Telegram] telegram_token is required"
            logger.error(err)
            self.report_startup_error(err)
            return

        try:
            from telegram.ext import (
                Application,
                MessageHandler,
                CommandHandler,
                filters,
            )
        except ImportError:
            err = (
                "[Telegram] python-telegram-bot is not installed. "
                "Run: pip install python-telegram-bot"
            )
            logger.error(err)
            self.report_startup_error(err)
            return

        # Run the asyncio event loop in a dedicated thread so the sync cow body
        # is untouched.
        self._loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._async_main(Application, MessageHandler, CommandHandler, filters))
            except Exception as e:
                logger.error(f"[Telegram] event loop crashed: {e}", exc_info=True)
                self.report_startup_error(str(e))
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass
                logger.info("[Telegram] event loop exited")

        self._loop_thread = threading.Thread(target=_run_loop, daemon=True, name="telegram-loop")
        self._loop_thread.start()
        # Block startup() until the loop thread exits, matching other channels'
        # behaviour (startup is a blocking call).
        self._loop_thread.join()

    async def _async_main(self, Application, MessageHandler, CommandHandler, filters):
        """Build Application, register handlers, and run polling."""
        builder = Application.builder().token(self.bot_token)

        # Proxy: prefer telegram_proxy config, fall back to HTTPS_PROXY env var
        proxy_url = conf().get("telegram_proxy", "") or os.environ.get("HTTPS_PROXY", "")
        if proxy_url:
            try:
                builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
                logger.info(f"[Telegram] using proxy: {proxy_url}")
            except Exception as e:
                logger.warning(f"[Telegram] proxy config failed, fallback to direct: {e}")

        # Media uploads (photo/voice/video/document) over a proxy can be slow,
        # bump read/write/connect/pool timeouts.
        builder = (
            builder
            .read_timeout(60)
            .write_timeout(120)
            .connect_timeout(30)
            .pool_timeout(30)
        )

        application = builder.build()
        self._application = application
        self._bot = application.bot

        # Fetch our own username (needed for @-mention matching in groups)
        try:
            me = await self._bot.get_me()
            self.bot_username = me.username or ""
            self.name = self.bot_username  # ChatChannel uses self.name to strip @-mention
            logger.info(f"[Telegram] Bot logged in as @{self.bot_username} (id={me.id})")
        except Exception as e:
            err = f"[Telegram] get_me failed: {e}"
            logger.error(err)
            self.report_startup_error(err)
            return

        # Register the command menu (failure is non-fatal)
        if conf().get("telegram_register_commands", True):
            try:
                from telegram import BotCommand
                cmds = [BotCommand(name, desc) for name, desc in TELEGRAM_BOT_COMMANDS]
                await self._bot.set_my_commands(cmds)
                logger.info(f"[Telegram] Registered {len(cmds)} bot commands")
            except Exception as e:
                logger.warning(f"[Telegram] set_my_commands failed: {e}")

        # Handlers:
        # 1) /cancel uses the fast-path
        application.add_handler(CommandHandler("cancel", self._on_cancel))
        # 2) Normal messages (text + media)
        application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, self._on_message))
        # 3) Other slash commands are forwarded as plain text for the agent to handle
        application.add_handler(MessageHandler(filters.COMMAND, self._on_command_passthrough))

        # Start polling. drop_pending_updates avoids replaying backlog after restart.
        # Transient "Server disconnected" / RemoteProtocolError during get_updates
        # are common over proxies/flaky networks; PTB's network loop auto-retries,
        # so we only need to keep the noise down (see _quiet_polling_network_errors).
        self._quiet_polling_network_errors()
        logger.info("[Telegram] Starting long polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            # Long-poll hold time on the server side; smaller value = reconnect more
            # often but each hung connection fails faster.
            timeout=30,
            # Retry forever on transient get_updates network errors instead of giving up.
            bootstrap_retries=-1,
        )
        self.report_startup_success()
        logger.info("[Telegram] ✅ Telegram bot ready, polling for updates")

        # Block until stop()
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            try:
                await application.updater.stop()
                await application.stop()
                await application.shutdown()
            except Exception as e:
                logger.warning(f"[Telegram] shutdown error: {e}")

    @staticmethod
    def _quiet_polling_network_errors():
        """Downgrade PTB's noisy 'Exception happened while polling for updates' logs.

        These transient get_updates errors (RemoteProtocolError / NetworkError /
        TimedOut, typically over a proxy) are auto-retried by PTB's network loop,
        so logging the full traceback at ERROR is just noise. We attach a filter
        that drops these specific records while leaving real errors untouched.
        """
        import logging

        class _PollingNoiseFilter(logging.Filter):
            _NEEDLES = (
                "Exception happened while polling for updates",
                "Server disconnected without sending a response",
            )

            def filter(self, record: logging.LogRecord) -> bool:
                try:
                    msg = record.getMessage()
                except Exception:
                    return True
                if any(n in msg for n in self._NEEDLES):
                    # Keep a single-line breadcrumb at DEBUG, drop the traceback.
                    logger.debug(f"[Telegram] transient polling network error (auto-retrying): {msg.splitlines()[0]}")
                    return False
                return True

        noise_filter = _PollingNoiseFilter()
        for name in ("telegram.ext.Updater", "telegram.ext._updater", "telegram.ext"):
            logging.getLogger(name).addFilter(noise_filter)

    def stop(self):
        logger.info("[Telegram] stop() called")
        self._stop_event.set()
        if self._loop_thread and self._loop_thread.is_alive():
            try:
                self._loop_thread.join(timeout=10)
            except Exception:
                pass
        logger.info("[Telegram] stop() completed")

    # ------------------------------------------------------------------
    # Inbound: telegram update -> ChatMessage -> ChatChannel.produce
    # ------------------------------------------------------------------

    async def _on_cancel(self, update, _context):
        """Fast-path: /cancel calls cancel_session directly without going through agent."""
        try:
            from agent.protocol import get_cancel_registry
            session_id = self._compute_session_id(update)
            cancelled = get_cancel_registry().cancel_session(session_id)
            text = "Current task cancelled." if cancelled else "No running task to cancel."
            await update.effective_message.reply_text(text)
            logger.info(f"[Telegram] /cancel session={session_id}, cancelled={cancelled}")
        except Exception as e:
            logger.error(f"[Telegram] /cancel error: {e}", exc_info=True)
            try:
                await update.effective_message.reply_text(f"⚠️ /cancel failed: {e}")
            except Exception:
                pass

    async def _on_command_passthrough(self, update, _context):
        """All non-/cancel commands fall through to plain message handling."""
        await self._on_message(update, _context)

    async def _on_message(self, update, _context):
        """Telegram update entry: parse message -> build ChatMessage -> produce()."""
        try:
            message = update.effective_message
            chat = update.effective_chat
            if not message or not chat:
                return

            # Idempotent dedup
            msg_uid = f"{chat.id}:{message.message_id}"
            if self._received_msgs.get(msg_uid):
                return
            self._received_msgs[msg_uid] = True

            is_group = chat.type in ("group", "supergroup")

            # Debug log: helpful when group messages are silently dropped
            if is_group:
                logger.debug(
                    f"[Telegram] group update received: chat_id={chat.id}, "
                    f"text={(message.text or message.caption or '')[:40]!r}, "
                    f"reply_to_bot={bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.username == self.bot_username)}"
                )

            # Group trigger gate (silently drop if not triggered)
            if is_group and not self._should_reply_in_group(update):
                logger.debug(f"[Telegram] group message not triggered (need @{self.bot_username} or reply), skip")
                return

            # Parse message type + download media if needed.
            # Media messages with caption return both the local path and the caption text.
            ctype, content, caption = await self._parse_message(message)
            if ctype is None:
                logger.debug(f"[Telegram] unsupported message type, skip. msg={message}")
                return

            # Strip @bot mention for group text/caption
            if is_group and self.bot_username:
                if ctype == ContextType.TEXT and content:
                    content = self._strip_at_mention(content)
                if caption:
                    caption = self._strip_at_mention(caption)

            tg_msg = TelegramMessage(
                update,
                is_group=is_group,
                bot_username=self.bot_username,
                ctype=ctype,
                content=content,
            )
            tg_msg.is_at = is_group  # If we got here in a group, the bot is mentioned/replied

            # File cache: standalone media goes into cache, the next text query attaches them
            from channel.file_cache import get_file_cache
            file_cache = get_file_cache()
            session_id = self._compute_session_id(update)

            # Media + caption together: treat as a complete query and bypass the cache
            if ctype in (ContextType.IMAGE, ContextType.FILE) and caption:
                tag = "image" if ctype == ContextType.IMAGE else "file"
                merged_text = f"{caption}\n[{tag}: {content}]"
                tg_msg.ctype = ContextType.TEXT
                tg_msg.content = merged_text
                ctype = ContextType.TEXT
                logger.info(f"[Telegram] Media+caption merged for session {session_id}")
                # fallthrough to the TEXT branch below

            elif ctype == ContextType.IMAGE:
                file_cache.add(session_id, content, file_type="image")
                logger.info(f"[Telegram] Image cached for session {session_id}, waiting for query...")
                return
            elif ctype == ContextType.FILE:
                file_cache.add(session_id, content, file_type="file")
                logger.info(f"[Telegram] File cached for session {session_id}: {content}")
                return

            if ctype == ContextType.TEXT:
                cached_files = file_cache.get(session_id)
                if cached_files:
                    refs = []
                    for fi in cached_files:
                        ftype = fi["type"]
                        tag = ftype if ftype in ("image", "video") else "file"
                        refs.append(f"[{tag}: {fi['path']}]")
                    tg_msg.content = (tg_msg.content or "") + "\n" + "\n".join(refs)
                    file_cache.clear(session_id)
                    logger.info(f"[Telegram] Attached {len(cached_files)} cached file(s) to query")

            # Dispatch to cow main pipeline (reuses ChatChannel._compose_context routing)
            context = self._compose_context(
                tg_msg.ctype,
                tg_msg.content,
                isgroup=is_group,
                msg=tg_msg,
            )
            if context:
                context["session_id"] = session_id
                context["receiver"] = str(chat.id)
                context["telegram_chat_id"] = chat.id
                context["telegram_reply_to_msg_id"] = message.message_id if is_group else None
                self.produce(context)
            logger.debug(f"[Telegram] received: type={ctype}, content={str(tg_msg.content)[:80]}")

        except Exception as e:
            logger.error(f"[Telegram] _on_message error: {e}", exc_info=True)

    async def _parse_message(self, message):
        """Parse a telegram message and return (ctype, content, caption).

        - content is text for ContextType.TEXT, otherwise the local file path
        - caption is the optional text accompanying a media message; empty for plain text
        """
        caption = (message.caption or "").strip()

        if message.photo:
            largest = message.photo[-1]
            path = await self._download_file(largest.file_id, suffix=".jpg")
            return (ContextType.IMAGE, path, caption) if path else (None, None, "")

        if message.voice or message.audio:
            audio_obj = message.voice or message.audio
            suffix = ".ogg" if message.voice else (
                "." + (audio_obj.mime_type.split("/")[-1] if getattr(audio_obj, "mime_type", "") else "mp3")
            )
            path = await self._download_file(audio_obj.file_id, suffix=suffix)
            return (ContextType.VOICE, path, caption) if path else (None, None, "")

        if message.video or message.video_note:
            video_obj = message.video or message.video_note
            path = await self._download_file(video_obj.file_id, suffix=".mp4")
            return (ContextType.FILE, path, caption) if path else (None, None, "")

        if message.document:
            doc = message.document
            ext = ""
            if doc.file_name and "." in doc.file_name:
                ext = "." + doc.file_name.rsplit(".", 1)[-1]
            path = await self._download_file(doc.file_id, suffix=ext, original_name=doc.file_name)
            if not path:
                return (None, None, "")
            # Image-typed documents (user picked "send as file") are treated as images
            mime = (doc.mime_type or "").lower()
            if mime.startswith("image/"):
                return (ContextType.IMAGE, path, caption)
            return (ContextType.FILE, path, caption)

        if message.text:
            return (ContextType.TEXT, message.text.strip(), "")

        return (None, None, "")

    async def _download_file(self, file_id: str, suffix: str = "", original_name: str = ""):
        """Download via bot.get_file into the local tmp dir; return path or None on failure."""
        try:
            f = await self._bot.get_file(file_id)
            tmp_dir = TelegramMessage.get_tmp_dir()
            base = original_name or f"{file_id}{suffix or ''}"
            # Prefix with file_id to avoid name collisions / weird chars
            safe_name = f"{file_id}_{base}" if original_name else base
            local_path = os.path.join(tmp_dir, safe_name)
            await f.download_to_drive(custom_path=local_path)
            logger.debug(f"[Telegram] downloaded file_id={file_id} -> {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"[Telegram] download_file failed (file_id={file_id}): {e}")
            return None

    # ------------------------------------------------------------------
    # Group trigger logic
    # ------------------------------------------------------------------

    def _should_reply_in_group(self, update) -> bool:
        """Decide whether to reply to a group message based on configuration."""
        mode = conf().get("telegram_group_trigger", "mention_or_reply")
        if mode == "all":
            return True

        message = update.effective_message
        if not message:
            return False

        # 1) Mentioned
        if self.bot_username and self._is_mentioned(message, self.bot_username):
            return True

        # 2) Reply to a bot message
        if mode == "mention_or_reply":
            reply = message.reply_to_message
            if reply and reply.from_user and reply.from_user.username == self.bot_username:
                return True

        return False

    @staticmethod
    def _is_mentioned(message, bot_username: str) -> bool:
        """Check whether entities/caption_entities contain a @mention of the bot."""
        bot_at = "@" + bot_username.lower()
        text = (message.text or message.caption or "").lower()
        if bot_at in text:
            return True
        # Also check entities strictly to support text_mention (no-username @)
        for ent in (message.entities or []) + (message.caption_entities or []):
            if ent.type == "mention":
                src = message.text or message.caption or ""
                if src[ent.offset: ent.offset + ent.length].lower() == bot_at:
                    return True
        return False

    def _strip_at_mention(self, content: str) -> str:
        """Strip @bot_username from group text (case-insensitive)."""
        if not content or not self.bot_username:
            return content
        pattern = re.compile(r"@" + re.escape(self.bot_username), re.IGNORECASE)
        return pattern.sub("", content).strip()

    @staticmethod
    def _compute_session_id(update) -> str:
        chat = update.effective_chat
        user = update.effective_user
        is_group = chat.type in ("group", "supergroup")
        if is_group:
            if conf().get("group_shared_session", True):
                return f"tg_group_{chat.id}"
            return f"tg_group_{chat.id}_{user.id}"
        return f"tg_user_{user.id}"

    # ------------------------------------------------------------------
    # Override _compose_context: skip the parent's group whitelist/at checks
    # (already handled in _on_message via _should_reply_in_group). Same idea
    # as the feishu channel.
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
            context.content = (content or "").strip()
            if "desire_rtype" not in context and conf().get("always_reply_voice"):
                context["desire_rtype"] = ReplyType.VOICE
        elif ctype == ContextType.VOICE:
            if "desire_rtype" not in context and (
                conf().get("voice_reply_voice") or conf().get("always_reply_voice")
            ):
                context["desire_rtype"] = ReplyType.VOICE

        return context

    # ------------------------------------------------------------------
    # Outbound: ChatChannel.send -> Telegram API
    # ------------------------------------------------------------------

    def send(self, reply: Reply, context: Context):
        """Called from cow's sync main thread; we marshal the coroutine onto the loop thread."""
        if self._loop is None or self._bot is None:
            logger.warning("[Telegram] bot not ready, drop reply")
            return

        chat_id = context.get("telegram_chat_id")
        reply_to = context.get("telegram_reply_to_msg_id")
        if chat_id is None:
            logger.warning("[Telegram] no telegram_chat_id in context, drop reply")
            return

        coro = self._async_send(reply, chat_id, reply_to)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            # Media uploads through a proxy can be slow; let PTB's own timeouts win
            future.result(timeout=180)
        except Exception as e:
            logger.error(f"[Telegram] send failed: {e}")

    # Number of retries for transient network errors (proxy hiccups etc.)
    _SEND_RETRIES = 2
    _SEND_RETRY_BACKOFF = 2.0  # seconds

    async def _send_with_retry(self, send_fn, *, label: str):
        """Run a single Telegram API call with retries for transient network errors."""
        from telegram.error import NetworkError, TimedOut
        last_err = None
        for attempt in range(self._SEND_RETRIES + 1):
            try:
                return await send_fn()
            except (NetworkError, TimedOut) as e:
                last_err = e
                if attempt >= self._SEND_RETRIES:
                    break
                wait = self._SEND_RETRY_BACKOFF * (attempt + 1)
                logger.warning(
                    f"[Telegram] {label} transient error (attempt {attempt + 1}/"
                    f"{self._SEND_RETRIES + 1}): {e}; retry in {wait}s"
                )
                await asyncio.sleep(wait)
        raise last_err

    async def _async_send(self, reply: Reply, chat_id, reply_to_msg_id):
        try:
            rtype = reply.type
            content = reply.content

            if rtype == ReplyType.TEXT or rtype == ReplyType.INFO or rtype == ReplyType.ERROR:
                # Telegram caps a single text message at 4096 chars; auto-split
                text = str(content) if content is not None else ""
                if not text:
                    return
                for chunk in _split_text(text, 4000):
                    await self._send_with_retry(
                        lambda c=chunk: self._bot.send_message(
                            chat_id=chat_id,
                            text=c,
                            reply_to_message_id=reply_to_msg_id,
                            # Avoid failing the whole send if reply_to was deleted
                            allow_sending_without_reply=True,
                        ),
                        label="send_message",
                    )

            elif rtype == ReplyType.IMAGE:
                # Already a local BytesIO; send it directly
                content.seek(0)
                await self._send_with_retry(
                    lambda: self._bot.send_photo(
                        chat_id=chat_id,
                        photo=content,
                        reply_to_message_id=reply_to_msg_id,
                        allow_sending_without_reply=True,
                    ),
                    label="send_photo",
                )

            elif rtype == ReplyType.IMAGE_URL:
                url = str(content)
                if url.startswith("file://"):
                    local = url[7:]
                    # Open inside the lambda so each retry gets a fresh stream
                    async def _send_local_photo():
                        with open(local, "rb") as f:
                            return await self._bot.send_photo(
                                chat_id=chat_id, photo=f,
                                reply_to_message_id=reply_to_msg_id,
                                allow_sending_without_reply=True,
                            )
                    await self._send_with_retry(_send_local_photo, label="send_photo(file)")
                else:
                    await self._send_with_retry(
                        lambda: self._bot.send_photo(
                            chat_id=chat_id, photo=url,
                            reply_to_message_id=reply_to_msg_id,
                            allow_sending_without_reply=True,
                        ),
                        label="send_photo(url)",
                    )

            elif rtype == ReplyType.VOICE:
                local = content[7:] if isinstance(content, str) and content.startswith("file://") else content
                async def _send_voice():
                    with open(local, "rb") as f:
                        return await self._bot.send_voice(
                            chat_id=chat_id, voice=f,
                            reply_to_message_id=reply_to_msg_id,
                            allow_sending_without_reply=True,
                        )
                await self._send_with_retry(_send_voice, label="send_voice")

            elif rtype == ReplyType.FILE:
                # Videos go through send_video, everything else through send_document
                local = content[7:] if isinstance(content, str) and content.startswith("file://") else content
                # File replies may carry an accompanying text caption
                caption = getattr(reply, "text_content", None) or None
                is_video = isinstance(local, str) and local.lower().endswith(
                    (".mp4", ".mov", ".avi", ".mkv", ".webm")
                )

                async def _send_file():
                    with open(local, "rb") as f:
                        if is_video:
                            return await self._bot.send_video(
                                chat_id=chat_id, video=f, caption=caption,
                                reply_to_message_id=reply_to_msg_id,
                                allow_sending_without_reply=True,
                            )
                        return await self._bot.send_document(
                            chat_id=chat_id, document=f, caption=caption,
                            reply_to_message_id=reply_to_msg_id,
                            allow_sending_without_reply=True,
                        )
                await self._send_with_retry(_send_file, label="send_video" if is_video else "send_document")

            else:
                # Fallback: send as plain text
                await self._send_with_retry(
                    lambda: self._bot.send_message(
                        chat_id=chat_id, text=str(content),
                        reply_to_message_id=reply_to_msg_id,
                        allow_sending_without_reply=True,
                    ),
                    label="send_message(fallback)",
                )

            logger.info(f"[Telegram] sent reply (type={rtype}, chat_id={chat_id})")

        except Exception as e:
            logger.error(f"[Telegram] _async_send error: {e}", exc_info=True)


def _split_text(text: str, limit: int):
    """Split long text preferring line breaks to keep markdown structure intact."""
    if len(text) <= limit:
        yield text
        return
    buf = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            yield "".join(buf)
            buf, size = [], 0
        # Hard-split single lines that exceed the limit
        while len(line) > limit:
            yield line[:limit]
            line = line[limit:]
        buf.append(line)
        size += len(line)
    if buf:
        yield "".join(buf)
