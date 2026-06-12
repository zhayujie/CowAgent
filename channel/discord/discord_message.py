"""
Discord message adapter.

Convert a discord.py Message into cow's unified ChatMessage.
File downloads are NOT performed here; the channel layer downloads
attachments on demand inside the async event loop.
"""
import os

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.utils import expand_path
from config import conf


class DiscordMessage(ChatMessage):
    """Wrap a discord.py Message into the unified ChatMessage."""

    def __init__(self, message, is_group: bool = False, bot_user_id: str = "",
                 ctype: ContextType = ContextType.TEXT, content: str = ""):
        super().__init__(message)
        # Basic fields
        self.msg_id = str(message.id)
        self.create_time = int(message.created_at.timestamp()) if message.created_at else 0
        self.ctype = ctype
        self.content = content

        author = message.author
        channel = message.channel

        # Sender / chat info
        from_user_id = str(author.id)
        from_user_nick = getattr(author, "display_name", None) or getattr(author, "name", None) or from_user_id
        self.from_user_id = from_user_id
        self.from_user_nickname = from_user_nick
        self.to_user_id = bot_user_id or "discord_bot"
        self.to_user_nickname = bot_user_id or "discord_bot"

        self.is_group = is_group
        if is_group:
            # Guild channel: other_user_id = channel_id, actual_user_id = sender id
            self.other_user_id = str(channel.id)
            self.other_user_nickname = getattr(channel, "name", None) or str(channel.id)
            self.actual_user_id = from_user_id
            self.actual_user_nickname = from_user_nick
        else:
            # DM: use channel_id so replies go back to the same DM channel
            self.other_user_id = str(channel.id)
            self.other_user_nickname = from_user_nick

        # Whether the bot was triggered by @-mention (set by channel layer)
        self.is_at = False

    @staticmethod
    def get_tmp_dir() -> str:
        """Local download directory, aligned with other channels (agent_workspace/tmp)."""
        workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
        tmp_dir = os.path.join(workspace_root, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir
