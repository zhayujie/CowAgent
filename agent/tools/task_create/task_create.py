"""task_create: hand a piece of work to the background task runner."""

from typing import Any, Dict

from agent.tools.base_tool import BaseTool, ToolResult
from common import i18n
from common.log import logger


class TaskCreateTool(BaseTool):
    name: str = "task_create"
    description: str = (
        "Start a background task: the work runs on its own, apart from this "
        "conversation, and its result is delivered back here when it finishes. "
        "Use it ONLY when the user explicitly asks for that — e.g. \"do it in "
        "the background\", \"handle it later\", \"let me know when it's done\", "
        "\"后台做\", \"做完通知我\". Never use it on your own initiative, and never "
        "for work you can finish right now in this reply. For something that "
        "should happen at a set time or repeatedly, use the scheduler instead.\n\n"
        "The task cannot see this conversation, so `prompt` must be a complete, "
        "self-contained brief: goal, inputs (paths, links, names), constraints "
        "and the expected output. After creating it, tell the user in one "
        "sentence that it is running in the background and stop; do not do the "
        "work yourself as well."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short title shown on the task board (under 30 characters).",
            },
            "prompt": {
                "type": "string",
                "description": "The complete brief for the task, written for someone who has not seen this conversation.",
            },
            "require_accept": {
                "type": "boolean",
                "description": "Set true only if the user asked to review the result before it counts as done.",
            },
        },
        "required": ["title", "prompt"],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}

    def is_available(self) -> bool:
        from agent.task.settings import is_enabled, task_settings

        return is_enabled() and task_settings()["chat_create"]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from agent.task import store as st
        from agent.task.origin import origin_from_context
        from agent.task.runner import create_task, origin_context_summary

        title = str(args.get("title") or "").strip()
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return ToolResult.fail("Error: prompt is required")

        agent = self.context
        context = getattr(agent, "_current_context", None)
        if context is not None and (context.get("is_task") or context.get("is_scheduled_task")):
            return ToolResult.fail("Error: a background run cannot start further background tasks")

        origin = origin_from_context(context)
        try:
            with agent.messages_lock:
                messages = list(agent.messages)
            origin["context_summary"] = origin_context_summary(messages)
        except Exception as e:
            logger.debug(f"[task_create] No conversation excerpt: {e}")

        agent_id = str(getattr(agent, "_current_agent_id", "") or origin.get("agent_id") or "")
        task = create_task(
            title=title[:60],
            prompt=prompt,
            agent_id=agent_id,
            source=st.SOURCE_CHAT,
            origin=origin,
            require_accept=bool(args.get("require_accept")),
        )
        return ToolResult.success(i18n.t(
            f"已创建后台任务 #{task['id']}「{task['title']}」，完成后会通知用户。"
            "现在用一句话告诉用户任务已在后台执行，然后结束本轮。",
            f"Background task #{task['id']} \"{task['title']}\" is created; the user "
            "will be notified when it finishes. Tell the user in one sentence that it "
            "is running in the background, then end this turn.",
        ))
