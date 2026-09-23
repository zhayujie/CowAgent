"""team_task — the team's shared task board."""

from __future__ import annotations

from agent.tools.base_tool import BaseTool, ToolResult
from agent.team_runtime import (
    TeamRuntimeError,
    resolve_agent_ref,
)
from common.log import logger

from ._shared import TeamCollabContext


class TeamTaskTool(BaseTool):
    """Create, claim, and complete tasks on the team's shared board."""

    name = "team_task"
    description = (
        "Work the shared team task board: create tasks, list them with "
        "their status and blockers, claim one (assign to yourself), update "
        "its progress, or close it. Everyone on the team sees the same "
        "board, and a task with unfinished blockers is blocked until they "
        "are completed. Use it for work that outlives a single message — "
        "otherwise prefer team_send."
    )
    params = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "get", "claim", "update", "complete"],
                "description": "create: add a task. list: the board (default). "
                "get: one task by id. claim: assign a task to yourself. "
                "update: edit subject/owner/blockers. complete: mark it done.",
            },
            "task_id": {
                "type": "string",
                "description": "The task id (get/claim/update/complete).",
            },
            "subject": {
                "type": "string",
                "description": "create: short title of the task.",
            },
            "description": {
                "type": "string",
                "description": "create/update: what needs doing, self-contained.",
            },
            "owner": {
                "type": "string",
                "description": "create/update: who owns the task — a teammate's "
                "id or name, or 'me'. Unowned tasks are up for grabs.",
            },
            "blocked_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "create/update: task ids this one waits on. The "
                "task stays blocked until every blocker is completed.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "update: the new status.",
            },
            "limit": {
                "type": "integer",
                "description": "list: at most this many tasks (default 50).",
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
            return ToolResult.fail("Could not resolve who is using the board")
        try:
            roster = collab.roster()
            action = str(params.get("action") or "list").strip().lower()
            handler = {
                "create": self._create,
                "list": self._list,
                "get": self._get,
                "claim": self._claim,
                "update": self._update,
                "complete": self._complete,
            }.get(action)
            if handler is None:
                return ToolResult.fail(
                    f"Unknown action '{action}'; use one of: create, list, "
                    "get, claim, update, complete"
                )
            return handler(collab, params, roster)
        except TeamRuntimeError as exc:
            return ToolResult.fail(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"[team_task] unexpected failure: {exc}")
            return ToolResult.fail(f"team_task failed: {exc}")

    # -- actions ------------------------------------------------------------

    def _resolve_owner(self, value, roster, self_id: str) -> Optional[dict]:
        if not value:
            return None
        if str(value).strip().lower() == "me":
            return {"id": self_id, "name": self._name_of(self_id, roster)}
        entry = resolve_agent_ref(value, roster)
        if entry is None:
            raise TeamRuntimeError(
                f"owner '{value}' is not on the team. "
                + ", ".join(f"{r['name']} ({r['id']})" for r in roster)
            )
        return {"id": entry["id"], "name": entry.get("name", "") or entry["id"]}

    @staticmethod
    def _name_of(agent_id: str, roster) -> str:
        for r in roster:
            if r.get("id") == agent_id:
                return r.get("name", "") or agent_id
        return agent_id

    def _create(self, collab, params, roster) -> ToolResult:
        owner = self._resolve_owner(params.get("owner"), roster, collab.self_agent_id)
        task = collab.store.create_task(
            collab.team_id,
            subject=str(params.get("subject", "")),
            description=str(params.get("description", "") or ""),
            owner=owner,
            blocked_by=params.get("blocked_by"),
            created_by_id=collab.self_agent_id,
            created_by_name=self._name_of(collab.self_agent_id, roster),
        )
        collab.store.append_activity(
            collab.team_id,
            kind="task",
            actor_id=collab.self_agent_id,
            actor_name=self._name_of(collab.self_agent_id, roster),
            text=f"created task {task['subject']}",
            detail={"task_id": task["id"]},
        )
        return ToolResult.success(
            {"task": task},
            display=f"Task created: [{task['id']}] {task['subject']}"
            + (f" (owner: {task['owner_name']})" if task.get("owner_name") else ""),
        )

    def _list(self, collab, params, roster) -> ToolResult:
        try:
            limit = max(1, min(int(params.get("limit") or 50), 200))
        except (TypeError, ValueError):
            limit = 50
        tasks = collab.store.list_tasks(collab.team_id)[:limit]
        lines = []
        for t in tasks:
            marker = "✓" if t["status"] == "completed" else ("→" if t["status"] == "in_progress" else "·")
            line = f"[{t['id']}] {marker} {t['subject']} — {t['status']}"
            if t.get("owner_name"):
                line += f" · owner {t['owner_name']}"
            if t.get("blocked_by"):
                blocked = collab.store.is_blocked(collab.team_id, t)
                line += f" · blocked by {', '.join(t['blocked_by'])}" + (
                    " (all done)" if not blocked else " (BLOCKED)"
                )
            lines.append(line)
        summary = (
            f"{len(tasks)} task(s) on the board:\n" + "\n".join(lines)
            if lines
            else "The team board is empty."
        )
        return ToolResult.success({"count": len(tasks), "tasks": tasks}, display=summary)

    def _get(self, collab, params, roster) -> ToolResult:
        task = collab.store.get_task(collab.team_id, params.get("task_id", ""))
        if task is None:
            return ToolResult.fail(
                f"No task with id '{params.get('task_id')}' on this board"
            )
        return ToolResult.success({"task": task}, display=self._describe(task, collab))

    def _claim(self, collab, params, roster) -> ToolResult:
        task = collab.store.get_task(collab.team_id, params.get("task_id", ""))
        if task is None:
            return ToolResult.fail(
                f"No task with id '{params.get('task_id')}' on this board"
            )
        updates = {
            "owner": collab.self_agent_id,
            "owner_name": self._name_of(collab.self_agent_id, roster),
        }
        if task["status"] == "pending":
            updates["status"] = "in_progress"
        updated = collab.store.update_task(collab.team_id, task["id"], updates)
        collab.store.append_activity(
            collab.team_id,
            kind="task",
            actor_id=collab.self_agent_id,
            actor_name=self._name_of(collab.self_agent_id, roster),
            text=f"claimed task {updated['subject']}",
            detail={"task_id": updated["id"]},
        )
        return ToolResult.success(
            {"task": updated},
            display=f"Claimed [{updated['id']}] {updated['subject']} — now owned by "
            f"{updated['owner_name']}"
            + (f", status {updated['status']}" if updates.get("status") else ""),
        )

    def _update(self, collab, params, roster) -> ToolResult:
        task_id = params.get("task_id", "")
        task = collab.store.get_task(collab.team_id, task_id)
        if task is None:
            return ToolResult.fail(f"No task with id '{task_id}' on this board")
        updates = {}
        for key in ("subject", "description", "status"):
            if params.get(key) is not None:
                updates[key] = params[key]
        if params.get("owner") is not None:
            owner = self._resolve_owner(params.get("owner"), roster, collab.self_agent_id)
            updates["owner"] = (owner or {}).get("id", "")
            updates["owner_name"] = (owner or {}).get("name", "")
        if params.get("blocked_by") is not None:
            updates["blocked_by"] = [str(b) for b in params["blocked_by"]]
        if not updates:
            return ToolResult.fail(
                "Nothing to update: pass subject, description, status, owner, or blocked_by"
            )
        updated = collab.store.update_task(collab.team_id, task_id, updates)
        collab.store.append_activity(
            collab.team_id,
            kind="task",
            actor_id=collab.self_agent_id,
            actor_name=self._name_of(collab.self_agent_id, roster),
            text=f"updated task {updated['subject']} ({', '.join(sorted(updates))})",
            detail={"task_id": updated["id"]},
        )
        return ToolResult.success({"task": updated}, display=self._describe(updated, collab))

    def _complete(self, collab, params, roster) -> ToolResult:
        return self._update(collab, {**params, "status": "completed"}, roster)

    def _describe(self, task: dict, collab) -> str:
        line = f"[{task['id']}] {task['subject']} — {task['status']}"
        if task.get("owner_name"):
            line += f" · owner {task['owner_name']}"
        if task.get("description"):
            line += f"\n{task['description']}"
        if task.get("blocked_by"):
            line += f"\nBlocked by: {', '.join(task['blocked_by'])}"
            if collab.store.is_blocked(collab.team_id, task):
                line += " — still blocked"
            else:
                line += " — all blockers done, ready to start"
        if task.get("blocks"):
            line += f"\nBlocks: {', '.join(task['blocks'])}"
        return line