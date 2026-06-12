"""
Telegram message adapter.

Convert a python-telegram-bot Update into cow's unified ChatMessage.
File downloads are NOT performed here; the channel layer triggers
bot.get_file() on demand because it requires the async event loop.
"""
import os

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.utils import expand_path
from config import conf


class TelegramMessage(ChatMessage):
    """Wrap a Telegram Update into the unified ChatMessage."""

    def __init__(self, update, is_group: bool = False, bot_username: str = "",
                 ctype: ContextType = ContextType.TEXT, content: str = ""):
        super().__init__(update)
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        # Basic fields
        self.msg_id = str(message.message_id) if message else ""
        self.create_time = int(message.date.timestamp()) if message and message.date else 0
        self.ctype = ctype
        self.content = content

        # Sender / chat info
        from_user_id = str(user.id) if user else "unknown"
        from_user_nick = (
            user.full_name if user and user.full_name else (user.username if user else "unknown")
        )
        self.from_user_id = from_user_id
        self.from_user_nickname = from_user_nick or from_user_id
        self.to_user_id = bot_username or "telegram_bot"
        self.to_user_nickname = bot_username or "telegram_bot"

        self.is_group = is_group
        if is_group:
            # Group: other_user_id = group_id, actual_user_id = sender id
            self.other_user_id = str(chat.id)
            self.other_user_nickname = chat.title or str(chat.id)
            self.actual_user_id = from_user_id
            self.actual_user_nickname = self.from_user_nickname
        else:
            self.other_user_id = from_user_id
            self.other_user_nickname = self.from_user_nickname

        # Whether the bot was triggered by @-mention or reply (set by channel layer)
        self.is_at = False

    @staticmethod
    def get_tmp_dir() -> str:
        """Local download directory, aligned with other channels (agent_workspace/tmp)."""
        workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
        tmp_dir = os.path.join(workspace_root, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir
