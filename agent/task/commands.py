"""Approve or reject from a chat reply ("通过 5" / "驳回 5 原因").

Checked before a message reaches the agent, and only when tasks are on. A
reply counts only for approvals that were sent to the same conversation, so
one chat cannot decide another's approvals.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from common import i18n
from common.log import logger

from agent.task import store as st
from agent.task.settings import is_enabled

_APPROVE_RE = re.compile(r"^(?:通过|批准|同意|approve)\s*#?(\d+)?\s*$", re.IGNORECASE)
_REJECT_RE = re.compile(r"^(?:驳回|拒绝|reject)(?:\s*#?(\d+))?(?:[\s,，:：]+(.*))?$", re.IGNORECASE | re.DOTALL)


def parse(text: str) -> Optional[Tuple[str, Optional[int], str]]:
    """``(decision, approval_id or None, note)`` when the text is a decision."""
    text = (text or "").strip()
    if not text or len(text) > 500:
        return None
    m = _APPROVE_RE.match(text)
    if m:
        return "approve", int(m.group(1)) if m.group(1) else None, ""
    m = _REJECT_RE.match(text)
    if m:
        return "reject", int(m.group(1)) if m.group(1) else None, (m.group(2) or "").strip()
    return None


def _belongs_to(approval: dict, channel_type: str, receiver: str) -> bool:
    origin = approval.get("origin") or {}
    return (
        bool(receiver)
        and origin.get("receiver") == receiver
        and (origin.get("channel_type") or "") == (channel_type or "")
    )


def _pending_for(channel_type: str, receiver: str) -> List[dict]:
    return [
        a for a in st.get_task_store().list_approvals(status=st.PENDING, limit=500)
        if _belongs_to(a, channel_type, receiver)
    ]


def try_handle(text: str, channel_type: str, receiver: str) -> Optional[str]:
    """Handle a decision reply; return the confirmation to send, or None to
    let the message through to the agent as usual."""
    if not is_enabled():
        return None
    parsed = parse(text)
    if parsed is None:
        return None
    decision, approval_id, note = parsed
    try:
        mine = _pending_for(channel_type, receiver)
    except Exception as e:
        logger.warning(f"[Task] Could not read approvals: {e}")
        return None
    if approval_id is None:
        if len(mine) != 1:
            if not mine:
                return None
            ids = "、".join(f"#{a['id']}" for a in mine[:10])
            return i18n.t(f"有多项待审批（{ids}），请带上编号，例如「通过 {mine[0]['id']}」。",
                          f"Several approvals are pending ({ids}); include the number, e.g. "
                          f"\"approve {mine[0]['id']}\".")
        target = mine[0]
    else:
        target = next((a for a in mine if a["id"] == approval_id), None)
        if target is None:
            return None

    from agent.task.approval import DecisionError, decide

    try:
        decide(target["id"], decision, note=note, via=channel_type or "im")
    except DecisionError as e:
        return i18n.t(f"审批 #{target['id']} 无法处理：{e}", f"Approval #{target['id']} could not be settled: {e}")
    except Exception as e:
        logger.error(f"[Task] Decision on #{target['id']} failed: {e}")
        return i18n.t(f"审批 #{target['id']} 处理失败：{e}", f"Approval #{target['id']} failed: {e}")

    if target.get("kind") == st.KIND_ACCEPT:
        if decision == "approve":
            return i18n.t(f"已验收 #{target['id']}，任务完成。", f"Accepted #{target['id']}; the task is done.")
        return i18n.t(f"已退回 #{target['id']}，任务会按你的意见返工。",
                      f"Sent #{target['id']} back; the task will be reworked per your note.")
    if decision == "approve":
        return i18n.t(f"已通过 #{target['id']}，继续执行。", f"Approved #{target['id']}; carrying on.")
    return i18n.t(f"已驳回 #{target['id']}，会按你的意见调整。",
                  f"Rejected #{target['id']}; adjusting per your note.")
