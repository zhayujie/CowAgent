"""
Agent Event Handler - Handles agent events and thinking process output
"""

from common import const
from common.log import logger

# Cap intermediate thinking messages on weixin to stay within send quota.
WEIXIN_THINKING_INSTANT_MAX = 7


class AgentEventHandler:
    """
    Handles agent events and optionally sends intermediate messages to channel
    """

    def __init__(self, context=None, original_callback=None):
        self.context = context
        self.original_callback = original_callback

        self.channel = None
        if context:
            self.channel = context.kwargs.get("channel") if hasattr(context, "kwargs") else None

        self.current_content = ""
        self.turn_number = 0

        channel_type = ""
        if context and hasattr(context, "kwargs"):
            channel_type = context.kwargs.get("channel_type", "") or ""
        self._is_weixin = channel_type == const.WEIXIN
        self._thinking_sent_count = 0
        self._merged_buf: list[str] = []

    def handle_event(self, event):
        event_type = event.get("type")
        data = event.get("data", {})

        if event_type == "turn_start":
            self._handle_turn_start(data)
        elif event_type == "message_update":
            self._handle_message_update(data)
        elif event_type == "message_end":
            self._handle_message_end(data)
        elif event_type == "reasoning_update":
            pass
        elif event_type == "tool_execution_start":
            self._handle_tool_execution_start(data)
        elif event_type == "tool_execution_end":
            self._handle_tool_execution_end(data)
        elif event_type == "tool_approval_required":
            self._handle_tool_approval_required(data)
        elif event_type == "agent_end":
            self._handle_agent_end(data)

        if self.original_callback:
            self.original_callback(event)

    def _handle_turn_start(self, data):
        self.turn_number = data.get("turn", 0)
        self.current_content = ""

    def _handle_message_update(self, data):
        delta = data.get("delta", "")
        self.current_content += delta

    def _handle_message_end(self, data):
        tool_calls = data.get("tool_calls", [])

        if tool_calls:
            if self.current_content.strip():
                logger.info(f"💭 {self.current_content.strip()[:200]}{'...' if len(self.current_content) > 200 else ''}")
                self._send_to_channel(self.current_content.strip())
        else:
            if self.current_content.strip():
                logger.debug(f"💬 {self.current_content.strip()[:200]}{'...' if len(self.current_content) > 200 else ''}")
            # Drain weixin buffer before final reply leaves chat_channel
            self._flush_merged_now()

        self.current_content = ""

    def _handle_agent_end(self, data):
        self._flush_merged_now()

    def _handle_tool_execution_start(self, data):
        pass

    def _handle_tool_execution_end(self, data):
        pass

    def _handle_tool_approval_required(self, data):
        """Handle a tool approval request event.

        Logs the request and sends a notification to the channel so the user
        is aware that a high-risk tool is waiting for their decision.
        """
        tool_name = data.get("tool_name", "unknown")
        risk_level = data.get("risk_level", "low")
        summary = data.get("summary", "")
        request_id = data.get("request_id", "")

        logger.info(
            f"[Approval] Tool '{tool_name}' (risk={risk_level}) "
            f"requires approval: {summary} "
            f"[request_id={request_id}]"
        )

        # Send a notification to the channel so the user sees the request
        message = (
            f"⚠️ 需要审批：工具 '{tool_name}'（风险等级：{risk_level}）\n"
            f"操作内容：{summary}\n"
            f"审批请求 ID：{request_id}\n"
            f"请使用 approve 或 reject 命令进行审批（超时 30 秒自动拒绝）"
        )
        self._send_to_channel(message)

    def _send_to_channel(self, message):
        if self.context and self.context.get("on_event"):
            return
        if not self.channel:
            return

        if not self._is_weixin:
            self._do_send(message)
            return

        if self._thinking_sent_count < WEIXIN_THINKING_INSTANT_MAX:
            self._do_send(message)
            self._thinking_sent_count += 1
            return

        self._merged_buf.append(message)

    def _flush_merged_now(self):
        if not self._merged_buf:
            return
        merged = "\n\n".join(self._merged_buf)
        count = len(self._merged_buf)
        self._merged_buf = []
        logger.debug(f"[AgentEventHandler] Flushing {count} merged thinking msgs, len={len(merged)}")
        self._do_send(merged)
        self._thinking_sent_count += 1

    def _do_send(self, message):
        try:
            from bridge.reply import Reply, ReplyType
            reply = Reply(ReplyType.TEXT, message)
            self.channel._send(reply, self.context)
        except Exception as e:
            logger.debug(f"[AgentEventHandler] Failed to send to channel: {e}")

    def log_summary(self):
        pass
