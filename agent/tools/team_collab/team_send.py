"""team_send — post a message to a teammate (or the whole team)."""

from __future__ import annotations

from agent.tools.base_tool import BaseTool, ToolResult
from agent.team_runtime import TeamRuntimeError, resolve_recipient, resolve_team_scope
from common.log import logger

from ._shared import TeamCollabContext, deliver_wakes


class TeamSendTool(BaseTool):
    """Leave a message for a teammate in the team's shared mailbox."""

    name = "team_send"
    description = (
        "Send a message to a teammate in this team conversation (or to "
        "'all' teammates at once). The message lands in their team inbox and "
        "they are woken to act on it. Use it to ask questions, hand over "
        "results, or coordinate — it does not wait for an answer; use "
        "agent_delegate when you need the result back before continuing."
    )
    params = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": (
                    "Who the message is for: a teammate's Agent ID (the @id "
                    "shown in the team conversation section), their name, or "
                    "'all' to broadcast to everyone on the team."
                ),
            },
            "message": {
                "type": "string",
                "description": "The message body. Be self-contained: the "
                "recipient only sees this text and its own inbox, not your "
                "conversation.",
            },
            "type": {
                "type": "string",
                "enum": ["info", "question", "result"],
                "description": "Optional message kind: 'question' when you "
                "need an answer, 'result' when you are reporting finished "
                "work, 'info' otherwise.",
            },
        },
        "required": ["to", "message"],
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
            return ToolResult.fail("Could not resolve who is sending this message")
        try:
            scope = resolve_team_scope(collab.roster(), collab.self_agent_id)
            content = str(params.get("message", "")).strip()
            if not content:
                return ToolResult.fail("The message body is empty")
            policy = collab.policy
            if len(content) > policy.max_message_chars:
                return ToolResult.fail(
                    f"Message is {len(content)} characters; the team limits "
                    f"messages to {policy.max_message_chars}. Summarize it."
                )
            recipients = resolve_recipient(
                params.get("to", ""), scope["roster"], collab.self_agent_id
            )
            records = collab.store.post_message(
                collab.team_id,
                sender_id=collab.self_agent_id,
                sender_name=collab.self_name or collab.self_agent_id,
                recipients=recipients,
                content=content,
                summary=content[:200],
                msg_type=str(params.get("type") or "info"),
                prune_limit=policy.max_mailbox_messages,
            )
            collab.store.append_activity(
                collab.team_id,
                kind="message",
                actor_id=collab.self_agent_id,
                actor_name=collab.self_name or collab.self_agent_id,
                text=f"→ {', '.join(r['to_name'] or r['to_id'] for r in records)}: "
                f"{content[:200]}",
                detail={"to": [r["to_id"] for r in records],
                        "type": records[0]["msg_type"] if records else "info"},
            )
        except TeamRuntimeError as exc:
            hint = collab.roster_hint()
            return ToolResult.fail(f"{exc} {hint}" if "not a teammate" in str(exc) else str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"[team_send] unexpected failure: {exc}")
            return ToolResult.fail(f"team_send failed: {exc}")

        delivery = deliver_wakes(
            collab,
            [{"id": r["to_id"], "name": r["to_name"]} for r in records],
            content,
            team_hint=f"the team conversation ({collab.team_id})",
        )
        woken = delivery.get("woken", [])
        if delivery.get("reason"):
            note = f"Delivered to the inbox; no live wake ({delivery['reason']})."
        elif delivery.get("not_woken"):
            note = (
                "Delivered to the inbox; could not wake "
                f"{', '.join(delivery['not_woken'])} right now."
            )
        elif len(records) == 1:
            note = f"Delivered; {records[0]['to_name'] or records[0]['to_id']} was woken."
        else:
            note = f"Delivered to {len(records)} teammates; {len(woken)} woken."
        return ToolResult.success(
            {
                "sent_to": [
                    {"id": r["to_id"], "name": r["to_name"], "message_id": r["id"]}
                    for r in records
                ],
                "woken": [w.get("id") for w in woken],
                "wake_note": note,
            },
            display=note,
        )