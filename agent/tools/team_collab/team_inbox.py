"""team_inbox — read your team mailbox and mark messages read."""

from __future__ import annotations

from agent.tools.base_tool import BaseTool, ToolResult
from agent.team_runtime import TeamRuntimeError
from common.log import logger

from ._shared import TeamCollabContext


def _render_message(record: dict) -> str:
    return (
        f"[{record['id']}] {record['created_at']} from "
        f"{record['from_name']} ({record['from_id']}) "
        f"type={record['msg_type']}\n"
        f"{record['content']}"
    )


class TeamInboxTool(BaseTool):
    """Read and acknowledge the messages addressed to you."""

    name = "team_inbox"
    description = (
        "Read your team inbox: messages teammates left you via team_send, "
        "newest first. Mark them read once you have acted on them so they "
        "stop counting as unread. Also reports your unread count."
    )
    params = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "mark_read"],
                "description": "list: show messages (default). mark_read: "
                "acknowledge message ids. read: list and then mark those "
                "messages read in one step.",
            },
            "message_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Message ids to mark read (mark_read).",
            },
            "unread_only": {
                "type": "boolean",
                "description": "list: only unread messages (default true).",
            },
            "limit": {
                "type": "integer",
                "description": "list: at most this many messages, newest "
                "first (default 20).",
            },
        },
        "required": [],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.agent_bridge = None
        self.current_context = None

    def execute(self, params: dict) -> ToolResult:
        if self.agent_bridge is None or self.current_context is None:
            return ToolResult.fail("Team collaboration is not attached to this turn")
        collab = TeamCollabContext(self, self.agent_bridge, self.current_context)
        if not collab.self_agent_id:
            return ToolResult.fail("Could not resolve who is reading this inbox")
        action = str(params.get("action") or "list").strip().lower()
        if action not in ("list", "read", "mark_read"):
            return ToolResult.fail(
                f"Unknown action '{action}'; use list, read, or mark_read"
            )
        try:
            unread_before = collab.store.unread_count(collab.team_id, collab.self_agent_id)
            messages = []
            changed = 0
            if action == "mark_read" and not params.get("message_ids"):
                return ToolResult.fail("mark_read needs the message_ids to acknowledge")
            if action in ("read", "mark_read"):
                ids = [str(i) for i in (params.get("message_ids") or [])]
                if action == "read":
                    if ids:
                        wanted = set(ids)
                        listed = collab.store.list_messages(
                            collab.team_id,
                            to_id=collab.self_agent_id,
                            limit=int(params.get("limit") or 20),
                        )
                        messages = [m for m in listed if m["id"] in wanted]
                        ids = [m["id"] for m in messages]
                    else:
                        unread_only = params.get("unread_only", True)
                        messages = collab.store.list_messages(
                            collab.team_id,
                            to_id=collab.self_agent_id,
                            unread_only=bool(unread_only),
                            limit=int(params.get("limit") or 20),
                        )
                        ids = [m["id"] for m in messages]
                if ids:
                    changed = collab.store.mark_messages_read(
                        collab.team_id, collab.self_agent_id, ids
                    )
            if action == "mark_read":
                payload = {
                    "marked_read": changed,
                    "unread_remaining": collab.store.unread_count(
                        collab.team_id, collab.self_agent_id
                    ),
                }
                summary = f"Marked {changed} message(s) read; unread remaining: {payload['unread_remaining']}."
                return ToolResult.success(payload, display=summary)
            if action == "list":
                unread_only = params.get("unread_only")
                if unread_only is None:
                    unread_only = True
                messages = collab.store.list_messages(
                    collab.team_id,
                    to_id=collab.self_agent_id,
                    unread_only=bool(unread_only),
                    limit=int(params.get("limit") or 20),
                )
        except TeamRuntimeError as exc:
            return ToolResult.fail(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"[team_inbox] unexpected failure: {exc}")
            return ToolResult.fail(f"team_inbox failed: {exc}")
        lines = [_render_message(m) for m in messages]
        payload = {
            "unread_before": unread_before,
            "count": len(messages),
            "messages": messages,
            "marked_read": changed if action == "read" else None,
            "unread_remaining": collab.store.unread_count(
                collab.team_id, collab.self_agent_id
            ),
        }
        if not lines:
            summary = f"Your team inbox is {'empty' if unread_only else 'clear'}; unread total: {payload['unread_remaining']}."
        else:
            summary = (
                f"{len(messages)} message(s):\n" + "\n\n".join(lines)
                + (f"\n\n(marked read: {changed})" if action == "read" else "")
            )
        return ToolResult.success(payload, display=summary)