"""Notices about tasks and approvals: fixed text templates and their delivery.

Cards are built from templates here, never written by the model, so what the
user is asked to approve is exactly what will run. Each notice goes to the
task's origin channel (filtered by the task's notify level) and, when one is
configured, to a webhook. The Web console reads pending approvals straight
from the store, so it needs nothing from this module.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional

from common import i18n
from common.log import logger

EVENT_APPROVAL_PENDING = "approval_pending"
EVENT_ACCEPT_PENDING = "accept_pending"
EVENT_TASK_DONE = "task_done"
EVENT_TASK_FAILED = "task_failed"

_ACTION_EVENTS = (EVENT_APPROVAL_PENDING, EVENT_ACCEPT_PENDING, EVENT_TASK_FAILED)

SUMMARY_LIMIT = 200
RESULT_PREVIEW_LIMIT = 300


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def action_summary(tool_name: str, tool_args: Any) -> str:
    """One line saying what a gated call would do."""
    args = tool_args if isinstance(tool_args, dict) else {}
    if tool_name == "bash" and args.get("command"):
        body = str(args["command"])
    elif tool_name in ("write", "edit") and args.get("path"):
        body = str(args["path"])
    else:
        try:
            body = json.dumps(args, ensure_ascii=False)
        except Exception:
            body = str(args)
    return _clip(f"{tool_name}  {body}", SUMMARY_LIMIT)


def _task_ref(task: Optional[dict]) -> str:
    if not task:
        return ""
    title = task.get("title") or ""
    return i18n.t(f"任务 #{task['id']}「{title}」", f"Task #{task['id']} \"{title}\"")


def approval_card(approval: dict, task: Optional[dict] = None) -> str:
    aid = approval["id"]
    label = approval.get("label") or approval.get("tool_name") or ""
    ref = _task_ref(task)
    if ref:
        head = i18n.t(f"【待审批 #{aid}】{ref}要执行：{label}",
                      f"[Approval #{aid}] {ref} wants to: {label}")
    else:
        head = i18n.t(f"【待审批 #{aid}】需要执行：{label}",
                      f"[Approval #{aid}] About to: {label}")
    lines = [
        head,
        i18n.t(f"动作：{approval.get('summary') or ''}", f"Action: {approval.get('summary') or ''}"),
        i18n.t(f"回复「通过 {aid}」或「驳回 {aid} 原因」",
               f"Reply \"approve {aid}\" or \"reject {aid} <reason>\""),
    ]
    return "\n".join(lines)


def accept_card(approval: dict, task: dict, result: str) -> str:
    aid = approval["id"]
    lines = [
        i18n.t(f"【待验收 #{aid}】{_task_ref(task)}已完成",
               f"[Review #{aid}] {_task_ref(task)} is done"),
        i18n.t(f"结果：{_clip(result, RESULT_PREVIEW_LIMIT)}",
               f"Result: {_clip(result, RESULT_PREVIEW_LIMIT)}"),
        i18n.t(f"回复「通过 {aid}」或「驳回 {aid} 修改意见」",
               f"Reply \"approve {aid}\" or \"reject {aid} <feedback>\""),
    ]
    return "\n".join(lines)


def done_text(task: dict, result: str) -> str:
    head = i18n.t(f"【任务 #{task['id']} 已完成】{task.get('title') or ''}",
                  f"[Task #{task['id']} done] {task.get('title') or ''}")
    return f"{head}\n\n{result}" if result else head


def failed_text(task: dict, error: str) -> str:
    return "\n".join([
        i18n.t(f"【任务 #{task['id']} 执行失败】{task.get('title') or ''}",
               f"[Task #{task['id']} failed] {task.get('title') or ''}"),
        i18n.t(f"原因：{_clip(error, SUMMARY_LIMIT)}", f"Reason: {_clip(error, SUMMARY_LIMIT)}"),
    ])


def _allowed(event: str, task: Optional[dict]) -> bool:
    level = (task or {}).get("notify_level") or "all"
    if level == "silent":
        return False
    if level == "action_only":
        return event in _ACTION_EVENTS
    return True


def _post_webhook(payload: Dict[str, Any]) -> None:
    from agent.task.settings import task_settings

    url = task_settings().get("notify_webhook")
    if not url:
        return

    def _send():
        try:
            import requests

            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code >= 400:
                logger.warning(f"[Task] Webhook answered {resp.status_code} for {payload.get('event')}")
        except Exception as e:
            logger.warning(f"[Task] Webhook delivery failed: {e}")

    threading.Thread(target=_send, daemon=True, name="task-webhook").start()


def _emit(event: str, text: str, task: Optional[dict] = None,
          approval: Optional[dict] = None, origin: Optional[dict] = None,
          push_origin: bool = True) -> None:
    from agent.task.origin import send_text_to_origin

    if not _allowed(event, task):
        return
    target = origin if origin is not None else (task or {}).get("origin") or {}
    # The Web console surfaces approvals in its own inbox; pushing the card
    # into the chat as well would put a reply-command into a page with buttons.
    if push_origin and target.get("channel_type") not in ("", "web", "task"):
        send_text_to_origin(target, text)
    payload = {
        "event": event,
        "task_id": (task or {}).get("id"),
        "approval_id": (approval or {}).get("id"),
        "title": (task or {}).get("title") or (approval or {}).get("label") or "",
        "text": text,
    }
    _post_webhook(payload)


def notify_approval_pending(approval: dict, task: Optional[dict] = None) -> None:
    origin = approval.get("origin") or (task or {}).get("origin") or {}
    _emit(EVENT_APPROVAL_PENDING, approval_card(approval, task), task, approval, origin)


def notify_accept_pending(approval: dict, task: dict, result: str) -> None:
    _emit(EVENT_ACCEPT_PENDING, accept_card(approval, task, result), task, approval)


def notify_task_failed(task: dict, error: str) -> None:
    _emit(EVENT_TASK_FAILED, failed_text(task, error), task)


def notify_task_done(task: dict, result: str) -> None:
    """Webhook only: the result itself is delivered by the runner."""
    _emit(EVENT_TASK_DONE, done_text(task, result), task, push_origin=False)
