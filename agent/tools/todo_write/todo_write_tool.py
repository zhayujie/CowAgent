import json
from dataclasses import dataclass
from typing import Dict, Callable, Optional, List

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger

STATUSES = ("pending", "in_progress", "completed")
MAX_TODOS = 10

_DESC_HEAD = (
    "Record and update the complete todo list for multi-step tasks, with at most 10 items. "
    "For tasks with two or more concrete steps, call this before starting and use one item per step. "
    "Skip trivial single-step tasks; do not split work just to use this tool. "
    "Always provide the complete list, replacing the previous list rather than merging changes. "
    "Pass an empty array to clear the list. "
)

_DESC_SINGLE = (
    "Mark the current item as in_progress while it is being worked on. "
    "At most one item may be in progress at a time. "
)

_DESC_PARALLEL = (
    "Mark every active item as in_progress. "
    "Multiple items may be in progress only when the work is actually parallel. "
)

_DESC_TAIL = (
    "Mark each item completed as soon as it is done, and update the complete list when steps change. "
    "Do not mark cancelled or failed work as completed. "
    "Continue the task immediately after writing the list; do not stop after listing todos."
)


def describe(allow_parallel: bool) -> str:
    """Share one parallelism policy across configuration, schema, and validation."""
    active_rule = _DESC_PARALLEL if allow_parallel else _DESC_SINGLE
    return _DESC_HEAD + active_rule + _DESC_TAIL


@dataclass(frozen=True)
class TodoContext:
    """Per-call authority injected by the engine for one conversation run.

    The commit callback writes only to this Agent, session, and run. It stores
    the complete normalized list atomically and returns its session-local
    version. Failures raise without changing the committed state, and retries
    of the same call are idempotent.
    """

    agent_id: str
    session_id: str
    run_id: str
    tool_call_id: str
    commit: Callable[[List[Dict[str, str]], str], int]


class TodoWriteTool(BaseTool):
    """Replace the complete todo list for the caller's conversation."""

    name: str = "todo_write"
    description: str = describe(False)

    params: dict = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "todos": {
                "type": "array",
                "maxItems": MAX_TODOS,
                "description": (
                    f"Complete todo list in execution order, with at most {MAX_TODOS} items; "
                    "replaces the previous list. Include every item on each call. "
                    "Pass an empty array to clear it."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "content": {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "A concise action item. After trimming whitespace, it must be non-empty and unique."
                            ),
                        },
                        "status": {
                            "type": "string",
                            "enum": list(STATUSES),
                            "description": (
                                "pending: not started; in_progress: currently active; completed: finished."
                            )
                        },
                    },
                    "required": ["content", "status"]
                }
            },
            "explanation": {
                "type": "string",
                "description": "Optional reason for this update.",
            }
        },
        "required": ["todos"],
    }

    def __init__(self, config: dict = None):
        super().__init__()
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise TypeError("todo_write configuration must be an object")
        self.config = dict(config)
        allow_parallel = config.get("allow_parallel_in_progress", False)

        if not isinstance(allow_parallel, bool):
            raise ValueError(
                "todo_write.allow_parallel_in_progress must be a boolean"
            )

        self.allow_parallel = allow_parallel
        self.description = describe(allow_parallel)

        self.todo_context: Optional[TodoContext] = None

    def _validate(self, params: dict):
        """Return the normalized list and explanation, or raise ValueError."""
        if not isinstance(params, dict):
            raise ValueError("parameters must be an object")

        if any(key not in ("todos", "explanation") for key in params):
            raise ValueError("only the todos and explanation parameters are supported")

        if "todos" not in params:
            raise ValueError("the required todos parameter is missing")

        incoming = params["todos"]
        if not isinstance(incoming, list):
            raise ValueError("todos must be an array; pass [] to clear the list")

        if len(incoming) > MAX_TODOS:
            raise ValueError(f"todos must contain at most {MAX_TODOS} items")

        explanation = params.get("explanation", "")
        if not isinstance(explanation, str):
            raise ValueError("explanation must be a string")
        explanation = explanation.strip()

        cleaned = []
        seen = set()
        active_count = 0

        for index, item in enumerate(incoming):
            prefix = f"todos[{index}]"

            if not isinstance(item, dict):
                raise ValueError(f"{prefix} must be an object")

            if set(item) != {"content", "status"}:
                raise ValueError(
                    f"{prefix} must contain exactly content and status"
                )

            content = item["content"]
            status = item["status"]

            if not isinstance(content, str):
                raise ValueError(f"{prefix}.content must be a string")
            if not isinstance(status, str):
                raise ValueError(f"{prefix}.status must be a string")

            content = content.strip()
            if not content:
                raise ValueError(f"{prefix}.content must not be empty")

            if status not in STATUSES:
                raise ValueError(f"{prefix}.status is invalid: {status!r}")

            if content in seen:
                raise ValueError(
                    f"{prefix}.content duplicates an earlier item: {content!r}"
                )

            seen.add(content)
            cleaned.append({"content": content, "status": status})
            active_count += int(status == "in_progress")

        if not self.allow_parallel and active_count > 1:
            raise ValueError(
                "the current configuration allows at most one in_progress item"
            )

        return cleaned, explanation

    @staticmethod
    def _counts(todos: List[Dict[str, str]]) -> Dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for item in todos:
            counts[item["status"]] += 1
        return counts

    @staticmethod
    def _display(todos, counts, explanation: str) -> str:
        if not todos:
            lines = ["Todo list cleared."]
        else:
            marks = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "completed": "[√]",
            }
            lines = [f"Todo progress: {counts['completed']}/{len(todos)} completed"]
            lines.extend(
                f"{marks[item['status']]} {item['content']}" for item in todos
            )

        if explanation:
            lines.extend(["", explanation])
        return "\n".join(lines)

    def execute(self, params: dict) -> ToolResult:
        # Validate the complete replacement before committing it.
        try:
            todos, explanation = self._validate(params)
        except ValueError as e:
            return ToolResult.fail(str(e))

        # A conversation-scoped commit callback is required.
        context = self.todo_context
        if not isinstance(context, TodoContext):
            return ToolResult.fail(
                "todo_write has no conversation commit callback; todos were not updated"
            )

        identities = (
            context.agent_id,
            context.session_id,
            context.run_id,
            context.tool_call_id,
        )

        if any(
                not isinstance(value, str) or not value.strip()
                for value in identities
        ):
            return ToolResult.fail(
                "todo_write conversation or call identity is incomplete; todos were not updated"
            )

        if not callable(context.commit):
            return ToolResult.fail("todo_write commit callback is unavailable")

        if self.is_cancelled():
            return ToolResult.fail("The task was cancelled; todos were not updated")

        counts = self._counts(todos)

        try:
            version = context.commit(
                [dict(item) for item in todos],
                explanation,
            )
        except Exception:
            logger.exception(
                "[TodoWrite] Commit failed, session=%s call=%s",
                context.session_id,
                context.tool_call_id,
            )
            return ToolResult.fail("Todo commit failed; check conversation storage and try again")

        # The commit callback must return a valid version.
        if type(version) is not int or version < 1:
            logger.error("[TodoWrite] Commit callback returned an invalid version")
            return ToolResult.fail(
                "Todo commit callback returned an invalid version; reload the conversation to verify its state"
            )

        self.emit_event(
            "todo_update",
            {
                "agent_id": context.agent_id,
                "session_id": context.session_id,
                "run_id": context.run_id,
                "tool_call_id": context.tool_call_id,
                "version": version,
                "todos": [dict(item) for item in todos],
                "counts": dict(counts),
                "explanation": explanation,
            },
        )

        return ToolResult.success(
            result=json.dumps(
                {
                    "todos": todos,
                    "counts":counts,
                    "version": version,
                },
                ensure_ascii=False,
            ),
            display=self._display(todos,counts,explanation),
        )
