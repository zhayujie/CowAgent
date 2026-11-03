"""What a conversation knows about its background tasks.

The conversation is where the user talks; the tasks are where the work runs.
So each chat turn carries a short list of this conversation's tasks (``turn_note``)
and the ``task`` tool reads and acts on them. Both are scoped to the
conversation the task was started from, so one chat never sees another's work.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from common import i18n
from common.log import logger

from agent.task import store as st
from agent.task.settings import is_enabled

# Finished tasks stay in the list this long, so "did it work?" has an answer.
RECENT_SECONDS = 6 * 3600
NOTE_LIMIT = 8
_SCAN_LIMIT = 200


def conversation_of(context) -> Dict[str, str]:
    if context is None:
        return {}
    return {
        "channel_type": str(context.get("channel_type") or ""),
        "receiver": str(context.get("receiver") or ""),
        "session_id": str(context.get("session_id") or ""),
    }


def belongs_to(task: dict, conversation: Dict[str, str]) -> bool:
    origin = task.get("origin") or {}
    session_id = conversation.get("session_id")
    if session_id and origin.get("session_id") == session_id:
        return True
    receiver = conversation.get("receiver")
    return (bool(receiver) and origin.get("receiver") == receiver
            and (origin.get("channel_type") or "") == conversation.get("channel_type", ""))


def _worth_listing(task: dict, now: float) -> bool:
    if task["status"] in st.ACTIVE_STATUSES:
        return True
    if now - (task.get("finished_at") or task.get("updated_at") or 0) > RECENT_SECONDS:
        return False
    # A scheduled run's output was delivered here already; only its failure is news.
    return task.get("source") != st.SOURCE_SCHEDULE or task["status"] == st.FAILED


def conversation_tasks(conversation: Dict[str, str], limit: int = NOTE_LIMIT) -> List[dict]:
    """This conversation's unfinished tasks and recently finished ones, the
    most recently updated first."""
    now = time.time()
    found = []
    for task in st.get_task_store().list_tasks(limit=_SCAN_LIMIT):
        if belongs_to(task, conversation) and _worth_listing(task, now):
            found.append(task)
            if len(found) >= limit:
                break
    return found


def _span(seconds: float) -> str:
    if seconds < 60:
        return i18n.t("不到 1 分钟", "under 1 min")
    return i18n.t(f"{int(seconds // 60)} 分钟", f"{int(seconds // 60)} min")


def status_line(task: dict, now: Optional[float] = None) -> str:
    now = now or time.time()
    status = task["status"]
    if status == st.QUEUED:
        return i18n.t("排队中", "queued")
    if status == st.RUNNING:
        span = _span(now - (task.get("started_at") or now))
        return i18n.t(f"执行中，已用时{span}", f"running for {span}")
    if status == st.WAITING:
        if task.get("wait_type") == st.WAIT_ACCEPT:
            return i18n.t("已出结果，等用户验收", "result ready, waiting for the user's review")
        return i18n.t("等用户审批", "waiting for the user's approval")
    ago = _span(now - (task.get("finished_at") or now))
    if status == st.DONE:
        return i18n.t(f"已完成（{ago}前）", f"done ({ago} ago)")
    if status == st.FAILED:
        reason = " ".join(str(task.get("error") or "").split())[:80]
        return i18n.t(f"失败（{ago}前）：{reason}", f"failed ({ago} ago): {reason}")
    return i18n.t("已停止", "stopped")


def task_line(task: dict, now: Optional[float] = None) -> str:
    return f"#{task['id']}「{task.get('title') or ''}」{status_line(task, now)}"


def recent_steps(task: dict, limit: int = 6) -> List[str]:
    """The last things the task's run did, read from its own session."""
    try:
        from agent.task.notify import action_summary
        from agent.task.runner import _get_bridge

        store = _get_bridge().get_conversation_store(task.get("agent_id") or None)
        messages = store.load_messages(task["session_id"], max_turns=2)
    except Exception as e:
        logger.debug(f"[Task] No progress for task #{task.get('id')}: {e}")
        return []
    steps = []
    for msg in messages:
        if msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if block.get("type") == "tool_use":
                steps.append(action_summary(block.get("name") or "", block.get("input") or {})[:160])
            elif block.get("type") == "text" and str(block.get("text") or "").strip():
                steps.append(" ".join(str(block["text"]).split())[:160])
    return steps[-limit:]


def _clock(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""


def task_detail(task: dict, result_chars: int = 1500) -> str:
    lines = [
        f"#{task['id']} {task.get('title') or ''}",
        i18n.t("状态：", "Status: ") + status_line(task),
        i18n.t("创建：", "Created: ") + _clock(task.get("created_at")),
    ]
    if task.get("started_at"):
        lines.append(i18n.t("开始：", "Started: ") + _clock(task["started_at"]))
    if task.get("finished_at"):
        lines.append(i18n.t("结束：", "Finished: ") + _clock(task["finished_at"]))
    if (task.get("run_count") or 0) > 1:
        lines.append(i18n.t(f"已执行 {task['run_count']} 轮", f"Rounds run: {task['run_count']}"))
    approvals = st.get_task_store().list_approvals(status=st.PENDING, task_id=task["id"], limit=5)
    for approval in approvals:
        lines.append(i18n.t("待用户确认：", "Waiting on the user: ")
                     + f"#{approval['id']} {approval.get('summary') or approval.get('tool_name') or ''}"[:200])
    if task["status"] in st.ACTIVE_STATUSES:
        steps = recent_steps(task)
        if steps:
            lines.append(i18n.t("最近进展：", "Recent progress:"))
            lines.extend(f"- {s}" for s in steps)
    if task.get("result"):
        result = str(task["result"])
        clipped = result[:result_chars] + ("…" if len(result) > result_chars else "")
        lines.append(i18n.t("结果：", "Result:") + "\n" + clipped)
    if task.get("error") and task["status"] != st.DONE:
        lines.append(i18n.t("错误：", "Error: ") + str(task["error"])[:500])
    return "\n".join(lines)


def turn_note(context) -> str:
    """The list of this conversation's tasks for the model to read on this
    turn, or "" when there is nothing to say. Never stored in the history."""
    if context is None or context.get("is_task") or context.get("is_scheduled_task") \
            or context.get("is_delegated_task"):
        return ""
    try:
        if not is_enabled():
            return ""
        conversation = conversation_of(context)
        tasks = conversation_tasks(conversation)
    except Exception as e:
        logger.debug(f"[Task] No task list for this turn: {e}")
        return ""
    if not tasks:
        return ""
    now = time.time()
    lines = [f"- {task_line(t, now)}" for t in tasks]
    guide = i18n.t(
        "这些任务在后台独立执行，结果会发回这个对话。用户问起进展时据此回答，要细节用 task 的 get；"
        "用户要修改、补充或继续某个任务时，用 task 的 follow 转交给它，要停止就用 cancel。"
        "不要在对话里自己去做这些任务的工作，也不要为同一件事再建新任务；除非用户说不用后台、直接在这里做，"
        "这时先 cancel 再做。指的是哪个任务不清楚时先问用户。",
        "These tasks run on their own in the background and send their results back to this "
        "conversation. When the user asks how they are going, answer from this list and use "
        "task get for details. When the user wants to change, add to or continue one, pass it "
        "on with task follow; to stop one, use task cancel. Do not do these tasks' work here "
        "yourself or create another task for the same work, unless the user says to do it "
        "here instead of in the background: then cancel it first and do it. If it is unclear "
        "which task the user means, ask.",
    )
    head = i18n.t("[本会话的后台任务，截至此刻]", "[This conversation's background tasks, as of now]")
    return "\n".join([head, *lines, guide])
