"""
Slack message adapter.

Convert a Slack event payload into cow's unified ChatMessage.
File downloads are NOT performed here; the channel layer downloads files
on demand because it needs the bot token for authenticated download URLs.
"""
import os

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.utils import expand_path
from config import conf


class SlackMessage(ChatMessage):
    """Wrap a Slack event into the unified ChatMessage."""

    def __init__(self, event: dict, is_group: bool = False, bot_user_id: str = "",
                 ctype: ContextType = ContextType.TEXT, content: str = ""):
        super().__init__(event)
        # Basic fields
        self.msg_id = event.get("client_msg_id") or event.get("ts") or ""
        try:
            self.create_time = int(float(event.get("ts", 0)))
        except (TypeError, ValueError):
            self.create_time = 0
        self.ctype = ctype
        self.content = content

        # Sender / chat info
        from_user_id = event.get("user", "unknown")
        channel_id = event.get("channel", "")
        self.from_user_id = from_user_id
        self.from_user_nickname = from_user_id
        self.to_user_id = bot_user_id or "slack_bot"
        self.to_user_nickname = bot_user_id or "slack_bot"

        self.is_group = is_group
        if is_group:
            # Channel chat: other_user_id = channel_id, actual_user_id = sender id
            self.other_user_id = channel_id
            self.other_user_nickname = channel_id
            self.actual_user_id = from_user_id
            self.actual_user_nickname = from_user_id
        else:
            # DM: use channel_id so replies go back to the same DM channel
            self.other_user_id = channel_id or from_user_id
            self.other_user_nickname = from_user_id

        # Whether the bot was triggered by @-mention (set by channel layer)
        self.is_at = False

    @staticmethod
    def get_tmp_dir() -> str:
        """Local download directory, aligned with other channels (agent_workspace/tmp)."""
        workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
        tmp_dir = os.path.join(workspace_root, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir
