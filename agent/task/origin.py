"""Where a task or an approval came from, and how to reach that place again.

An origin is a small dict captured from the inbound context: the channel, the
receiver and the conversation. It is what results and notices are delivered
back to, using the same channel lookup scheduled tasks use.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger


def origin_from_context(context: Optional[Context]) -> Dict[str, Any]:
    if context is None:
        return {}
    try:
        channel_type = str(context.get("channel_type") or "")
        origin = {
            "channel_type": channel_type,
            "receiver": str(context.get("receiver") or ""),
            "is_group": bool(context.get("isgroup", False)),
            "session_id": str(context.get("session_id") or ""),
            "instance_id": str(context.get("instance_id") or ""),
            "agent_id": str(context.get("agent_id") or ""),
        }
        msg = context.get("msg")
        staff_id = getattr(msg, "sender_staff_id", None) if msg is not None else None
        if staff_id:
            origin["dingtalk_sender_staff_id"] = staff_id
        return origin
    except Exception as e:
        logger.debug(f"[Task] Could not read origin from context: {e}")
        return {}


def origin_from_scheduled_action(action: dict, agent_id: str = "") -> Dict[str, Any]:
    """The origin of a scheduled task: its delivery target."""
    action = action or {}
    from agent.tools.scheduler.integration import _primary_channel_type

    origin = {
        "channel_type": _primary_channel_type(action.get("channel_type")),
        "receiver": str(action.get("receiver") or ""),
        "is_group": bool(action.get("is_group", False)),
        "session_id": str(action.get("notify_session_id") or action.get("receiver") or ""),
        "instance_id": str(action.get("instance_id") or ""),
        "agent_id": agent_id or "",
    }
    if action.get("dingtalk_sender_staff_id"):
        origin["dingtalk_sender_staff_id"] = action["dingtalk_sender_staff_id"]
    if action.get("silent"):
        origin["silent"] = True
    return origin


def is_deliverable(origin: Optional[dict]) -> bool:
    origin = origin or {}
    return bool(origin.get("channel_type") and origin.get("receiver"))


def delivery_context(origin: dict, content: str = "") -> Context:
    """A context that lets ``channel.send`` reach the origin, as scheduled
    deliveries build it."""
    channel_type = origin.get("channel_type") or ""
    is_group = bool(origin.get("is_group"))
    context = Context(ContextType.TEXT, content)
    context["receiver"] = origin.get("receiver") or ""
    context["isgroup"] = is_group
    context["session_id"] = origin.get("session_id") or origin.get("receiver") or ""
    context["agent_id"] = origin.get("agent_id") or ""
    context["channel_type"] = channel_type
    if origin.get("instance_id"):
        context["instance_id"] = origin["instance_id"]
    if channel_type == "web":
        context["request_id"] = f"task_push_{uuid.uuid4().hex[:12]}"
    elif channel_type == "feishu":
        context["receive_id_type"] = "chat_id" if is_group else "open_id"
        context["msg"] = None
    elif channel_type == "dingtalk":
        context["msg"] = None
        if not is_group and origin.get("dingtalk_sender_staff_id"):
            context["dingtalk_sender_staff_id"] = origin["dingtalk_sender_staff_id"]
    elif channel_type == "wecom_bot":
        context["msg"] = None
    return context


def send_to_origin(origin: dict, reply: Reply) -> bool:
    """Push one reply to the origin's channel. Never raises."""
    if not is_deliverable(origin) or reply is None:
        return False
    try:
        from agent.tools.scheduler.integration import _resolve_delivery_channel

        channel_type = origin.get("channel_type")
        context = delivery_context(origin, str(reply.content or ""))
        channel = _resolve_delivery_channel(
            channel_type, origin.get("instance_id") or "", origin.get("receiver") or ""
        )
        if channel is None:
            logger.warning(f"[Task] No channel to deliver to: {channel_type}")
            return False
        if channel_type == "web" and hasattr(channel, "request_to_session"):
            channel.request_to_session[context["request_id"]] = context["session_id"]
            if hasattr(channel, "request_to_agent") and context.get("agent_id"):
                channel.request_to_agent[context["request_id"]] = context["agent_id"]
        channel.send(reply, context)
        return True
    except Exception as e:
        logger.warning(f"[Task] Delivery to {origin.get('channel_type')} failed: {e}")
        return False


def serving_web_channel():
    """The web console's channel while it is serving, else None. Never
    creates one: the console can be switched off."""
    try:
        from channel.web.core.channel import WebChannel

        web = WebChannel.peek()
    except Exception:
        return None
    return web if getattr(web, "_sse_janitor_started", False) else None


def send_text_to_origin(origin: dict, text: str) -> bool:
    if not text:
        return False
    return send_to_origin(origin, Reply(ReplyType.TEXT, text))
