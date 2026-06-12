"""Evolution undo tool.

Lets the main chat agent roll back a previous self-evolution when the user asks
("undo the last learning"). The rollback itself is a deterministic FILE RESTORE
from the snapshot taken before the evolution — the model only supplies the
backup_id it reads from the [EVOLUTION] record in the conversation. No LLM-driven
re-editing is involved, so a restore can never make things worse.
"""

from agent.tools.base_tool import BaseTool, ToolResult


class EvolutionUndoTool(BaseTool):
    """Restore memory/skill files to the state before a self-evolution."""

    name: str = "evolution_undo"
    description: str = (
        "Undo a previous self-evolution (self-learning) by restoring the "
        "memory/skill files to their state before that learning. Use this when "
        "the user asks to undo / revert / roll back the last self-learning. "
        "Find the backup_id in the most recent [EVOLUTION] record in the "
        "conversation and pass it here."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "backup_id": {
                "type": "string",
                "description": (
                    "The backup_id from the [EVOLUTION] record to restore "
                    "(e.g. '20260607-155551-850')."
                ),
            }
        },
        "required": ["backup_id"],
    }

    def execute(self, args: dict):
        backup_id = (args.get("backup_id") or "").strip()
        if not backup_id:
            return ToolResult.fail("Error: backup_id is required")
        try:
            from agent.memory.config import get_default_memory_config
            from agent.evolution.backup import restore_backup

            workspace_dir = get_default_memory_config().get_workspace()
            ok = restore_backup(workspace_dir, backup_id)
            if ok:
                return ToolResult.success(
                    f"Restored memory/skills to the state before evolution "
                    f"{backup_id}. The previous self-learning has been undone."
                )
            return ToolResult.fail(
                f"Could not find or restore backup {backup_id}. It may have "
                f"expired or already been rolled back."
            )
        except Exception as e:
            return ToolResult.fail(f"Error during undo: {e}")
