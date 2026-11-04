"""Chat replies settled before a message reaches the agent: approve or reject
("通过 5" / "驳回 5 原因"), typed out or sent quoting the approval's card.
Any other reply, including one quoting a task's notice, goes to the agent,
which acts on the task with the ``task`` tool.

Checked only when tasks are on. A decision counts only for approvals whose
notices were sent to the same conversation, so one chat cannot act on
another's.
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

# The heading an approval or review card starts with (see notify). Only the
# start of the quote is searched, so a card quoted by a channel that puts a
# title before it is still found.
_APPROVAL_NOTICE_RE = re.compile(r"[【\[](?:待审批|待验收|Approval|Review) #(\d+)")
_NOTICE_HEAD = 80
# How channels put a quote in front of the reply (weixin, feishu).
_QUOTE_WRAPPERS = ("[引用: {}]\n", "[Quoted message]\n{}\n[/Quoted message]\n\n")


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


def quoted_approval(quoted: str) -> Optional[int]:
    """The approval a quoted message is the card of, if it is one."""
    m = _APPROVAL_NOTICE_RE.search((quoted or "").strip()[:_NOTICE_HEAD])
    return int(m.group(1)) if m else None


def own_text(text: str, quoted: str) -> str:
    """The reply without the quote the channel put in front of it."""
    text = text or ""
    if quoted:
        for wrapper in _QUOTE_WRAPPERS:
            block = wrapper.format(quoted)
            at = text.find(block)
            if at >= 0:
                return (text[:at] + text[at + len(block):]).strip()
    return text.strip()


def _belongs_to(item: dict, channel_type: str, receiver: str) -> bool:
    from agent.task.overview import belongs_to

    return belongs_to(item, {"channel_type": channel_type or "", "receiver": receiver or ""})


def _pending_for(channel_type: str, receiver: str) -> List[dict]:
    return [
        a for a in st.get_task_store().list_approvals(status=st.PENDING, limit=500)
        if _belongs_to(a, channel_type, receiver)
    ]


def try_handle(text: str, channel_type: str, receiver: str, quoted: str = "") -> Optional[str]:
    """Handle a decision reply; return the confirmation to send, or None to let
    the message through to the agent as usual. ``quoted`` is the text of the
    message the reply quotes, if any: quoting a card stands in for its number."""
    if not is_enabled():
        return None
    quoted = (quoted or "").strip()
    parsed = parse(own_text(text, quoted))
    if parsed is None:
        return None
    decision, approval_id, note = parsed
    if approval_id is None:
        approval_id = quoted_approval(quoted)
    return _decide(decision, approval_id, note, channel_type, receiver)


def _decide(decision: str, approval_id: Optional[int], note: str,
            channel_type: str, receiver: str) -> Optional[str]:
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

