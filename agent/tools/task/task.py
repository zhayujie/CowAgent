"""task: let a conversation run and manage its background tasks."""

from typing import Any, Dict

from agent.tools.base_tool import BaseTool, ToolResult
from common import i18n
from common.log import logger

ACTIONS = ("list", "get", "create", "follow", "cancel", "delete")
# The first few tasks a conversation creates say how to undo it or turn it off.
CREATE_HINT_LIMIT = 3

_INTRO = (
    "Manage this conversation's background tasks: work that runs on its own, apart "
    "from this chat, and sends its result back here when it finishes. A task's status "
    "changes outside this chat, so when the user asks how one is going, check it with "
    "list or get instead of answering from earlier messages.\n\n"
    "Actions:\n"
    "- list: this conversation's tasks with their status.\n"
    "- get (task_id): one task in detail: times, what it is waiting on, its latest "
    "steps while running, and its result or error once finished.\n"
)
_CREATE = (
    "- create (title, prompt): start a new task. ONLY when the user explicitly asks "
    "for background work, e.g. \"do it in the background\", \"let me know when it's "
    "done\", \"后台做\", \"做完通知我\". Never on your own initiative, and never for "
    "work you can finish right now in this reply. For a set time or a repeat, use the "
    "scheduler instead. The task cannot see this chat, so `prompt` must be a complete, "
    "self-contained brief: goal, inputs (paths, links, names), constraints and the "
    "expected output.\n"
)
_MANAGE = (
    "- follow (task_id, message): pass the user's new instruction to an existing task, "
    "e.g. \"add a chart to #3\". A running task reads it after its current step, a "
    "finished one carries on with its full context, and one waiting for review is "
    "reworked.\n"
    "- cancel (task_id): stop a task the user wants stopped. If they would rather have "
    "it done here (\"do it now\", \"直接做\"), cancel it and do the work in this reply.\n"
    "- delete (task_id): remove a task and its record; only when the user explicitly "
    "asks to delete it.\n\n"
    "When the user is talking about an existing task, act on that task with follow or "
    "cancel; do not do its work here yourself or create a new task for it. A message "
    "quoting a task's notice (\"【任务 #3 …】\", \"[Task #3 …]\", or a review card naming "
    "task #3) is about that task, though a question about the result can just be "
    "answered. If it is unclear which task they mean, ask. After {after}, tell the "
    "user in one sentence what happens next and end the turn."
)
_CREATE_PARAMS = {
    "title": {
        "type": "string",
        "description": "For create: short title shown on the task board (under 30 characters).",
    },
    "prompt": {
        "type": "string",
        "description": "For create: the complete brief, written for someone who has not seen this conversation.",
    },
    "require_accept": {
        "type": "boolean",
        "description": "For create: true only if the user asked to review the result before it counts as done.",
    },
}


CREATE_HINT_ZH = "不需要放后台的话，回复「直接做」就会停掉它、在这里接着做；也可以在「配置 → Agent 配置」里关闭「对话中创建任务」。"
CREATE_HINT_EN = ("Don't need it in the background? Reply \"do it now\" and it stops and gets done "
                  "here, or turn off \"Create tasks from chat\" under Config → Agent Configuration.")


def _follow_text(mode, tid: int):
    """What the user is told after the instruction reached the task, by how
    ``reply_to_task`` took it; None when it did not."""
    if mode == "steer":
        return i18n.t(f"已补充给正在执行的任务 #{tid}。", f"Passed on to task #{tid}, which is running.")
    if mode == "queued":
        return i18n.t(f"已记下，任务 #{tid} 接着做时会一并处理。",
                      f"Noted; task #{tid} takes it up when it carries on.")
    if mode == "rework":
        return i18n.t(f"已退回任务 #{tid}，按用户的意见修改后再发回来。",
                      f"Sent task #{tid} back; it will be revised per the user's note and sent back.")
    if mode == "reopened":
        return i18n.t(f"任务 #{tid} 接着处理中，完成后结果会发回这个对话。",
                      f"Task #{tid} is carrying on; its result will be sent back to this conversation.")
    return None


def _can_create() -> bool:
    from agent.task.settings import chat_create_enabled

    return chat_create_enabled()


def _shows_create_hint() -> bool:
    from agent.task import store as st

    try:
        made = st.get_task_store().list_tasks(source=st.SOURCE_CHAT, limit=CREATE_HINT_LIMIT + 1)
    except Exception:
        return False
    return len(made) <= CREATE_HINT_LIMIT


class TaskTool(BaseTool):
    """Without chat creation the tool still reads and acts on existing tasks;
    ``create`` just drops out of what the model is shown."""

    name: str = "task"

    def __init__(self, config: dict = None):
        self.config = config or {}

    @property
    def description(self) -> str:
        if _can_create():
            return _INTRO + _CREATE + _MANAGE.format(after="create or follow")
        return _INTRO + _MANAGE.format(after="follow")

    @property
    def params(self) -> dict:
        can_create = _can_create()
        actions = [a for a in ACTIONS if can_create or a != "create"]
        properties = {
            "action": {"type": "string", "enum": actions},
            "task_id": {
                "type": "integer",
                "description": "The task number, e.g. 3 for #3. For get, follow, cancel and delete.",
            },
            **(_CREATE_PARAMS if can_create else {}),
            "message": {
                "type": "string",
                "description": "For follow: the user's instruction for the task, in full.",
            },
        }
        return {"type": "object", "properties": properties, "required": ["action"]}

    def is_available(self) -> bool:
        from agent.task.settings import is_enabled

        return is_enabled()

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        context = getattr(self.context, "_current_context", None)
        if context is not None and (context.get("is_task") or context.get("is_scheduled_task")):
            return ToolResult.fail("Error: a background run cannot manage background tasks")
        action = str(args.get("action") or "").strip()
        if action not in ACTIONS:
            return ToolResult.fail(f"Error: action must be one of {', '.join(ACTIONS)}")
        if action == "list":
            return self._list(context)
        if action == "create":
            if not _can_create():
                return ToolResult.fail(i18n.t(
                    "对话中创建后台任务已关闭，请直接在这次回复里完成。",
                    "Creating background tasks from a conversation is turned off; do the work in this reply.",
                ))
            return self._create(args, context)
        task = self._own_task(args.get("task_id"), context)
        if isinstance(task, ToolResult):
            return task
        if action == "get":
            from agent.task.overview import task_detail

            return ToolResult.success(task_detail(task))
        if action == "follow":
            return self._follow(task, str(args.get("message") or "").strip())
        if action == "cancel":
            return self._cancel(task)
        return self._delete(task)

    def _list(self, context) -> ToolResult:
        from agent.task import overview

        tasks = overview.conversation_tasks(overview.conversation_of(context))
        if not tasks:
            return ToolResult.success(i18n.t(
                "这个对话目前没有后台任务（6 小时内也没有已结束的）。",
                "This conversation has no background tasks (none finished in the last 6 hours either).",
            ))
        return ToolResult.success("\n".join(overview.task_line(t) for t in tasks))

    def _own_task(self, raw_id, context):
        """The task the call names, if this conversation may act on it. The
        console sees every task on its board; a chat only its own."""
        from agent.task import overview
        from agent.task import store as st

        try:
            task_id = int(str(raw_id).strip().lstrip("#"))
        except (TypeError, ValueError):
            return ToolResult.fail("Error: task_id is required and must be a number")
        task = st.get_task_store().get_task(task_id)
        conversation = overview.conversation_of(context)
        if not task or (conversation.get("channel_type") != "web"
                        and not overview.belongs_to(task, conversation)):
            return ToolResult.fail(i18n.t(
                f"没有找到这个对话的任务 #{task_id}。",
                f"No task #{task_id} in this conversation.",
            ))
        return task

    def _create(self, args: Dict[str, Any], context) -> ToolResult:
        from agent.task import store as st
        from agent.task.notify import task_link
        from agent.task.origin import origin_from_context
        from agent.task.runner import create_task, origin_context_summary

        title = str(args.get("title") or "").strip()
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return ToolResult.fail("Error: prompt is required for create")
        agent = self.context
        origin = origin_from_context(context)
        try:
            with agent.messages_lock:
                messages = list(agent.messages)
            origin["context_summary"] = origin_context_summary(messages)
        except Exception as e:
            logger.debug(f"[task] No conversation excerpt: {e}")

        agent_id = str(getattr(agent, "_current_agent_id", "") or origin.get("agent_id") or "")
        task = create_task(
            title=title[:60],
            prompt=prompt,
            agent_id=agent_id,
            source=st.SOURCE_CHAT,
            origin=origin,
            require_accept=bool(args.get("require_accept")),
        )
        text = i18n.t(
            f"已创建后台任务 #{task['id']}「{task['title']}」，完成后结果会发回这个对话。"
            "现在用一句话回复用户：说清楚要做的具体事情和完成后会拿到什么，并带上任务编号，"
            f"例如「好的，后台整理本周周报，完成后发给你（#{task['id']}）」。然后结束本轮，不要自己再做这件事。",
            f"Background task #{task['id']} \"{task['title']}\" is created; its result will be "
            "sent back to this conversation. Reply to the user in one sentence naming the concrete "
            "work and what they will get when it is done, with the task number, e.g. \"Sure, I'll "
            f"put together this week's report in the background and send it to you (#{task['id']}).\" "
            "Then end this turn; do not do the work yourself as well.",
        )
        if _shows_create_hint():
            text += i18n.t(
                f"\n用户还不熟悉这个功能：在那句话之后另起一行，原样附上「{CREATE_HINT_ZH}」",
                f"\nThe user is new to this: on a new line after that sentence, add exactly "
                f"\"{CREATE_HINT_EN}\"",
            )
        return ToolResult.success(text, display=i18n.t(
            f"已转到后台执行：{task_link(task)}",
            f"Running in the background: {task_link(task)}",
        ))

    def _follow(self, task: dict, message: str) -> ToolResult:
        from agent.task import store as st
        from agent.task.notify import task_link
        from agent.task.runner import reply_to_task

        if not message:
            return ToolResult.fail("Error: message is required for follow")
        if task.get("source") == st.SOURCE_SCHEDULE:
            return ToolResult.fail(i18n.t(
                f"任务 #{task['id']} 是定时任务的一次执行，它的后续结果不会发回这里。"
                "要改以后每次的执行内容，请修改对应的定时任务。",
                f"Task #{task['id']} is one run of a schedule; what it does next is not sent "
                "back here. To change future runs, edit the schedule instead.",
            ))
        text = _follow_text(reply_to_task(task["id"], message), task["id"])
        if not text:
            return ToolResult.fail(i18n.t(
                f"任务 #{task['id']} 现在没能接收这条补充，请稍后再试。",
                f"Task #{task['id']} could not take this instruction right now; try again shortly.",
            ))
        return ToolResult.success(
            text + i18n.t("用一句话告诉用户，然后结束本轮。", " Tell the user in one sentence and end this turn."),
            display=f"{task_link(task)} ← {message[:80]}",
        )

    def _cancel(self, task: dict) -> ToolResult:
        from agent.task import store as st
        from agent.task.runner import cancel_task

        if task["status"] not in st.ACTIVE_STATUSES:
            return ToolResult.success(i18n.t(
                f"任务 #{task['id']} 已经结束，不需要停止。",
                f"Task #{task['id']} has already finished; nothing to stop.",
            ))
        if not cancel_task(task["id"]):
            return ToolResult.fail(i18n.t(f"没能停止任务 #{task['id']}。", f"Could not stop task #{task['id']}."))
        return ToolResult.success(i18n.t(f"已停止任务 #{task['id']}。", f"Task #{task['id']} is stopped."))

    def _delete(self, task: dict) -> ToolResult:
        from agent.task.runner import delete_task

        if not delete_task(task["id"]):
            return ToolResult.fail(i18n.t(f"没能删除任务 #{task['id']}。", f"Could not delete task #{task['id']}."))
        return ToolResult.success(i18n.t(f"已删除任务 #{task['id']}。", f"Task #{task['id']} is deleted."))
