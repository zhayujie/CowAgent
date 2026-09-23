"""Read-only view of one team conversation: mailbox, task board, activity feed.

The team collaboration tools (team_send / team_inbox / team_task) are how the
Agents reach this state during a conversation; this endpoint is how the console
shows the same state to the user. It reads the same shared store
(:mod:`agent.team_runtime`) and resolves the roster the same way the tools do —
session members stored under the conversation owner — and it writes nothing.
"""

from typing import List
import json

import web

from agent.team_runtime import TeamRuntimeError, get_team_store
from channel.web.core._common import _require_auth
from common.log import logger


def _team_roster(agent_registry, session_id: str, owner_id: str) -> List[dict]:
    """``[{id, name}]`` for everyone on the conversation, owner included.

    Mirrors ``TeamCollabContext.roster``: members are stored under the owner
    (host), ids go through ``get_addressed`` so a reserved alias like
    "default" resolves to the agent behind it, and unknown members are
    reported rather than dropped so the panel reflects what was configured.
    """
    from agent.workspace import session_prefs

    try:
        member_ids = list(
            session_prefs.get_prefs(session_id, owner_id).get("members") or []
        )
    except Exception as exc:
        logger.warning(f"[WebChannel] Could not read team members: {exc}")
        member_ids = []
    if owner_id and owner_id not in member_ids:
        member_ids.insert(0, owner_id)

    roster = []
    for member_id in member_ids:
        if not member_id or any(item["id"] == member_id for item in roster):
            continue
        profile = agent_registry.get_addressed(member_id, require_enabled=False)
        roster.append({"id": profile.id, "name": profile.name or profile.id})
    return roster


class TeamStateHandler:
    """GET /api/teams/{session_id}: one team's roster, mailbox, board, feed."""

    def GET(self, session_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            session_id = (session_id or "").strip()
            if not session_id:
                return json.dumps(
                    {"status": "error", "message": "session_id required"}
                )

            params = web.input(agent='', agent_id='', limit='')
            agent_id = params.agent_id or params.agent or None
            from agent.registry import get_agent_registry

            registry = get_agent_registry()
            owner = registry.get_addressed(agent_id, require_enabled=False)
            store = get_team_store()
            roster = _team_roster(registry, session_id, owner.id)

            limit = max(1, min(int(params.limit or 50), 200))
            tasks = [
                {**task, "blocked": store.is_blocked(session_id, task)}
                for task in store.list_tasks(session_id)
            ]

            return json.dumps({
                "status": "success",
                "team": {
                    "session_id": session_id,
                    "owner": {"id": owner.id, "name": owner.name or owner.id},
                    "members": roster,
                },
                "messages": store.list_messages(session_id, limit=limit),
                "tasks": tasks,
                "activity": store.get_activity(session_id, limit=limit)["items"],
            }, ensure_ascii=False)
        except TeamRuntimeError as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Team API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})