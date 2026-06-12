"""
Slack channel via Bolt for Python (Socket Mode).

Features:
- Direct message & channel chat (text / image / file)
- Channel trigger: @mention or reply in a thread the bot is in (configurable)
- /cancel fast-path matches Web channel behaviour
- Socket Mode: no public IP / callback URL required, works behind NAT

Implementation note:
    slack_bolt's SocketModeHandler is blocking and runs its own background
    threads. We start it in a dedicated thread so the rest of cow (sync) stays
    untouched. Inbound events are dispatched onto cow's existing sync
    ChatChannel.produce() pipeline; outbound send() calls the Slack Web API
    client directly (it is sync-safe).
"""

import os
import re
import threading

import requests

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.slack.slack_message import SlackMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from config import conf


@singleton
class SlackChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.bot_token = ""
        self.app_token = ""
        self.bot_user_id = ""  # used to strip @mention and ignore self messages
        self._app = None
        self._handler = None
        self._client = None
        self._loop_thread = None
        # Idempotent dedup; Slack retries event delivery on slow ack
        self._received_msgs = ExpiredDict(60 * 60 * 1)

        # Disable group whitelist / prefix checks (we handle triggering ourselves
        # in _should_reply_in_channel), aligned with telegram / feishu channels.
        conf()["group_name_white_list"] = ["ALL_GROUP"]
        conf()["single_chat_prefix"] = [""]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self):
        self.bot_token = conf().get("slack_bot_token", "")
        self.app_token = conf().get("slack_app_token", "")
        if not self.bot_token or not self.app_token:
            err = "[Slack] slack_bot_token and slack_app_token are both required"
            logger.error(err)
            self.report_startup_error(err)
            return

        # Guard against the common mistake of swapping the two tokens:
        # bot token must start with xoxb-, app-level token with xapp-.
        if not self.bot_token.startswith("xoxb-") or not self.app_token.startswith("xapp-"):
            err = (
                "[Slack] token type mismatch: slack_bot_token must start with 'xoxb-' "
                "and slack_app_token must start with 'xapp-' (they look swapped)"
            )
            logger.error(err)
            self.report_startup_error(err)
            return

        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            err = (
                "[Slack] slack_bolt is not installed. "
                "Run: pip install slack_bolt"
            )
            logger.error(err)
            self.report_startup_error(err)
            return

        try:
            self._app = App(token=self.bot_token)
            self._client = self._app.client

            # Resolve our own bot user id (needed for @mention strip / self-ignore)
            auth = self._client.auth_test()
            self.bot_user_id = auth.get("user_id", "")
            self.name = self.bot_user_id  # ChatChannel uses self.name to strip @-mention
            logger.info(f"[Slack] Bot logged in as user_id={self.bot_user_id}, team={auth.get('team')}")
        except Exception as e:
            err = f"[Slack] auth_test failed: {e}"
            logger.error(err)
            self.report_startup_error(err)
            return

        self._register_handlers()

        self._handler = SocketModeHandler(self._app, self.app_token)

        def _run():
            try:
                logger.info("[Slack] Starting Socket Mode connection...")
                self.report_startup_success()
                logger.info("[Slack] ✅ Slack bot ready, listening for events")
                self._handler.start()
            except Exception as e:
                logger.error(f"[Slack] socket mode crashed: {e}", exc_info=True)
                self.report_startup_error(str(e))
            finally:
                logger.info("[Slack] socket mode exited")

        self._loop_thread = threading.Thread(target=_run, daemon=True, name="slack-socket")
        self._loop_thread.start()
        # Block startup() until the handler thread exits, matching other channels'
        # behaviour (startup is a blocking call).
        self._loop_thread.join()

    def _register_handlers(self):
        app = self._app

        # app_mention: bot is @-mentioned in a channel
        @app.event("app_mention")
        def _on_app_mention(event, ack):
            ack()
            self._handle_event(event, is_group=True)

        # message: DMs and channel messages (including thread replies)
        @app.event("message")
        def _on_message(event, ack):
            ack()
            self._handle_message_event(event)

    def stop(self):
        logger.info("[Slack] stop() called")
        try:
            if self._handler is not None:
                self._handler.close()
        except Exception as e:
            logger.warning(f"[Slack] handler close error: {e}")
        if self._loop_thread and self._loop_thread.is_alive():
            try:
                self._loop_thread.join(timeout=10)
            except Exception:
                pass
        logger.info("[Slack] stop() completed")

    # ------------------------------------------------------------------
    # Inbound: slack event -> ChatMessage -> ChatChannel.produce
    # ------------------------------------------------------------------

    def _handle_message_event(self, event: dict):
        """Route a raw `message` event: skip bot/system noise, decide grouping."""
        try:
            logger.debug(
                f"[Slack] message event: channel_type={event.get('channel_type')}, "
                f"subtype={event.get('subtype')}, user={event.get('user')}, "
                f"ts={event.get('ts')}, thread_ts={event.get('thread_ts')}"
            )
            # Ignore bot messages (including our own) and message edits/deletes
            if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
                return
            if event.get("user") == self.bot_user_id:
                return

            channel_type = event.get("channel_type", "")
            # DM (im) is single chat; channel/group is group chat. app_mention
            # already covers channel @-mentions, so for plain channel messages we
            # only react when configured / thread-following.
            is_group = channel_type in ("channel", "group", "mpim")
            if is_group:
                # app_mention handler covers explicit @bot; here we only handle
                # follow-up replies in threads the bot participates in.
                if not self._should_reply_in_channel(event):
                    return
            self._handle_event(event, is_group=is_group)
        except Exception as e:
            logger.error(f"[Slack] _handle_message_event error: {e}", exc_info=True)

    def _handle_event(self, event: dict, is_group: bool):
        """Parse event -> build SlackMessage -> produce()."""
        try:
            channel_id = event.get("channel", "")
            ts = event.get("ts", "")
            if not channel_id:
                return

            # Idempotent dedup
            msg_uid = f"{channel_id}:{ts}"
            if self._received_msgs.get(msg_uid):
                return
            self._received_msgs[msg_uid] = True

            # Parse type + download media if needed.
            ctype, content, caption = self._parse_event(event)
            if ctype is None:
                logger.debug(f"[Slack] unsupported message type, skip. event={event}")
                return

            # Strip <@bot_user_id> mention from channel text
            if is_group and self.bot_user_id:
                if ctype == ContextType.TEXT and content:
                    content = self._strip_at_mention(content)
                if caption:
                    caption = self._strip_at_mention(caption)

            slack_msg = SlackMessage(
                event,
                is_group=is_group,
                bot_user_id=self.bot_user_id,
                ctype=ctype,
                content=content,
            )
            slack_msg.is_at = is_group  # if we reached here in a channel, bot is mentioned/threaded

            from channel.file_cache import get_file_cache
            file_cache = get_file_cache()
            session_id = self._compute_session_id(event, is_group)

            # Media + caption together: treat as a complete query and bypass the cache
            if ctype in (ContextType.IMAGE, ContextType.FILE) and caption:
                tag = "image" if ctype == ContextType.IMAGE else "file"
                merged_text = f"{caption}\n[{tag}: {content}]"
                slack_msg.ctype = ContextType.TEXT
                slack_msg.content = merged_text
                ctype = ContextType.TEXT
                logger.info(f"[Slack] Media+caption merged for session {session_id}")
                # fallthrough to the TEXT branch below

            elif ctype == ContextType.IMAGE:
                file_cache.add(session_id, content, file_type="image")
                logger.info(f"[Slack] Image cached for session {session_id}, waiting for query...")
                return
            elif ctype == ContextType.FILE:
                file_cache.add(session_id, content, file_type="file")
                logger.info(f"[Slack] File cached for session {session_id}: {content}")
                return

            if ctype == ContextType.TEXT:
                # Fast-path: /cancel mirrors Web channel behaviour
                if (content or "").strip().lower() in ("/cancel", "cancel"):
                    self._do_cancel(session_id, channel_id, event)
                    return

                cached_files = file_cache.get(session_id)
                if cached_files:
                    refs = []
                    for fi in cached_files:
                        ftype = fi["type"]
                        tag = ftype if ftype in ("image", "video") else "file"
                        refs.append(f"[{tag}: {fi['path']}]")
                    slack_msg.content = (slack_msg.content or "") + "\n" + "\n".join(refs)
                    file_cache.clear(session_id)
                    logger.info(f"[Slack] Attached {len(cached_files)} cached file(s) to query")

            # Reply in the originating thread when present, else start one on this msg
            thread_ts = event.get("thread_ts") or ts

            context = self._compose_context(
                slack_msg.ctype,
                slack_msg.content,
                isgroup=is_group,
                msg=slack_msg,
                # Replies go back into the thread, no manual @mention needed
                no_need_at=True,
            )
            if context:
                context["session_id"] = session_id
                context["receiver"] = channel_id
                context["slack_channel"] = channel_id
                context["slack_thread_ts"] = thread_ts if is_group else None
                self.produce(context)
            logger.debug(f"[Slack] received: type={ctype}, content={str(slack_msg.content)[:80]}")
        except Exception as e:
            logger.error(f"[Slack] _handle_event error: {e}", exc_info=True)

    def _do_cancel(self, session_id: str, channel_id: str, event: dict):
        """Fast-path: /cancel calls cancel_session directly without going through agent."""
        try:
            from agent.protocol import get_cancel_registry
            cancelled = get_cancel_registry().cancel_session(session_id)
            text = "Current task cancelled." if cancelled else "No running task to cancel."
            thread_ts = event.get("thread_ts") or event.get("ts")
            self._client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)
            logger.info(f"[Slack] /cancel session={session_id}, cancelled={cancelled}")
        except Exception as e:
            logger.error(f"[Slack] /cancel error: {e}", exc_info=True)

    def _parse_event(self, event: dict):
        """Parse a slack event and return (ctype, content, caption).

        - content is text for ContextType.TEXT, otherwise the local file path
        - caption is the optional text accompanying a file; empty for plain text
        """
        text = (event.get("text") or "").strip()
        files = event.get("files") or []

        if files:
            # Handle the first attachment; caption is the accompanying message text
            f = files[0]
            mimetype = (f.get("mimetype") or "").lower()
            url = f.get("url_private_download") or f.get("url_private")
            name = f.get("name") or f.get("id") or "file"
            if not url:
                return (None, None, "")
            path = self._download_file(url, name)
            if not path:
                return (None, None, "")
            if mimetype.startswith("image/"):
                return (ContextType.IMAGE, path, text)
            return (ContextType.FILE, path, text)

        if text:
            return (ContextType.TEXT, text, "")

        return (None, None, "")

    def _download_file(self, url: str, name: str):
        """Download a Slack private file (requires bot token auth) to local tmp dir."""
        try:
            headers = {"Authorization": f"Bearer {self.bot_token}"}
            resp = requests.get(url, headers=headers, timeout=60, stream=True)
            resp.raise_for_status()
            tmp_dir = SlackMessage.get_tmp_dir()
            # Sanitize the name and keep it unique-ish via the url tail
            safe_name = re.sub(r"[^\w.\-]", "_", name)
            local_path = os.path.join(tmp_dir, safe_name)
            with open(local_path, "wb") as fp:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fp.write(chunk)
            logger.debug(f"[Slack] downloaded {name} -> {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"[Slack] download_file failed ({name}): {e}")
            return None

    # ------------------------------------------------------------------
    # Channel trigger logic
    # ------------------------------------------------------------------

    def _should_reply_in_channel(self, event: dict) -> bool:
        """Decide whether to reply to a plain channel message (no @mention).

        app_mention already handles explicit @bot, so here we only deal with
        follow-up messages. `all` replies to every message; `mention_or_reply`
        replies inside threads the bot already participates in.
        """
        mode = conf().get("slack_group_trigger", "mention_or_reply")
        if mode == "all":
            return True
        if mode == "mention_only":
            return False
        # mention_or_reply: follow up only within an existing thread
        return bool(event.get("thread_ts"))

    def _strip_at_mention(self, content: str) -> str:
        """Strip <@BOT_USER_ID> from channel text."""
        if not content or not self.bot_user_id:
            return content
        pattern = re.compile(r"<@" + re.escape(self.bot_user_id) + r">", re.IGNORECASE)
        return pattern.sub("", content).strip()

    @staticmethod
    def _compute_session_id(event: dict, is_group: bool) -> str:
        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        if is_group:
            if conf().get("group_shared_session", True):
                return f"slack_channel_{channel_id}"
            return f"slack_channel_{channel_id}_{user_id}"
        return f"slack_user_{user_id}"

    # ------------------------------------------------------------------
    # Override _compose_context: skip the parent's group whitelist/at checks
    # (already handled via _should_reply_in_channel). Same idea as telegram.
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
    # Outbound: ChatChannel.send -> Slack Web API
    # ------------------------------------------------------------------

    def send(self, reply: Reply, context: Context):
        """Called from cow's sync main thread; Slack Web client is sync-safe."""
        if self._client is None:
            logger.warning("[Slack] client not ready, drop reply")
            return

        channel_id = context.get("slack_channel")
        thread_ts = context.get("slack_thread_ts")
        if not channel_id:
            logger.warning("[Slack] no slack_channel in context, drop reply")
            return

        try:
            self._do_send(reply, channel_id, thread_ts)
            logger.info(f"[Slack] sent reply (type={reply.type}, channel={channel_id})")
        except Exception as e:
            logger.error(f"[Slack] send failed: {e}", exc_info=True)

    def _do_send(self, reply: Reply, channel_id: str, thread_ts):
        rtype = reply.type
        content = reply.content

        if rtype in (ReplyType.TEXT, ReplyType.INFO, ReplyType.ERROR):
            text = str(content) if content is not None else ""
            if not text:
                return
            # Slack caps a message around 40k chars; split conservatively
            for chunk in _split_text(text, 3500):
                self._client.chat_postMessage(channel=channel_id, text=chunk, thread_ts=thread_ts)

        elif rtype == ReplyType.IMAGE:
            # Already a local BytesIO; upload it directly
            content.seek(0)
            self._client.files_upload_v2(
                channel=channel_id, file=content, filename="image.png", thread_ts=thread_ts,
            )

        elif rtype == ReplyType.IMAGE_URL:
            url = str(content)
            if url.startswith("file://"):
                local = url[7:]
                self._client.files_upload_v2(
                    channel=channel_id, file=local, thread_ts=thread_ts,
                )
            else:
                # Post the URL as text; Slack will unfurl it as an image preview
                self._client.chat_postMessage(channel=channel_id, text=url, thread_ts=thread_ts)

        elif rtype in (ReplyType.VOICE, ReplyType.FILE):
            local = content[7:] if isinstance(content, str) and content.startswith("file://") else content
            caption = getattr(reply, "text_content", None) or None
            self._client.files_upload_v2(
                channel=channel_id, file=local, initial_comment=caption, thread_ts=thread_ts,
            )

        else:
            # Fallback: send as plain text
            self._client.chat_postMessage(channel=channel_id, text=str(content), thread_ts=thread_ts)


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
