"""Approval gate: user rules checked at tool execution time, and what happens
once the user decides.

Nothing here is in the system prompt. A rule matches a tool call by tool name
and, optionally, a regular expression over the call's JSON arguments. A match
either refuses the call (``deny``) or parks it as a pending approval (``ask``)
and tells the model the action has not run. Approving runs the saved call
directly, never through the model, and then lets the conversation continue
with the outcome; rejecting continues it with the user's note. Neither path
keeps a thread waiting, so a decision survives a restart.
"""

from __future__ import annotations

import fnmatch
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from common import i18n
from common.log import logger

from agent.task import store as st
from agent.task.settings import disable_rule, is_enabled, task_settings

EXEC_RESULT_LIMIT = 4000


@dataclass
class GateDecision:
    action: str = "auto"  # auto | deny | ask | replay
    rule: Dict[str, Any] = field(default_factory=dict)
    approval: Optional[Dict[str, Any]] = None
    message: str = ""


AUTO = GateDecision()


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------

def _tool_matches(pattern: str, tool_name: str) -> bool:
    for part in str(pattern or "").split(","):
        part = part.strip()
        if part and (part == "*" or fnmatch.fnmatchcase(tool_name, part)):
            return True
    return False


def _args_text(arguments: Any) -> str:
    try:
        return json.dumps(arguments, ensure_ascii=False)
    except Exception:
        return str(arguments)


def _pattern_matches(pattern: str, text: str) -> bool:
    if not pattern:
        return True
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        # A pattern the user typed that is not a valid regex still means
        # something: match it as plain text rather than never matching.
        return pattern.lower() in text.lower()


def match_rule(rules: List[Dict[str, Any]], tool_name: str, arguments: Any) -> Optional[Dict[str, Any]]:
    """The first enabled rule that applies; ``deny`` rules win over ``ask``."""
    hit = None
    text = None
    for rule in rules:
        if not rule.get("enabled", True) or not _tool_matches(rule.get("tool"), tool_name):
            continue
        if rule.get("match"):
            if text is None:
                text = _args_text(arguments)
            if not _pattern_matches(rule["match"], text):
                continue
        if rule.get("action") == "deny":
            return rule
        if hit is None:
            hit = rule
    return hit


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

def check(agent, tool_name: str, arguments: Any) -> GateDecision:
    """Decide what to do with one tool call. Cheap when nothing is configured."""
    if not is_enabled():
        return AUTO
    rules = task_settings()["approval_rules"]
    if not rules:
        return AUTO
    rule = match_rule(rules, tool_name, arguments)
    if rule is None:
        return AUTO

    label = rule.get("label") or tool_name
    if rule.get("action") == "deny":
        return GateDecision(
            action="deny", rule=rule,
            message=i18n.t(
                f"该操作已被用户规则禁止（{label}），未执行。请换一种方式完成，或告知用户。",
                f"This action is blocked by a user rule ({label}) and did not run. "
                "Find another way, or tell the user.",
            ),
        )

    store = st.get_task_store()
    session_id = str(getattr(agent, "_current_session_id", "") or "")
    agent_id = str(getattr(agent, "_current_agent_id", "") or "")

    earlier = store.recent_decision(session_id, tool_name, arguments)
    if earlier is not None:
        return GateDecision(action="replay", rule=rule, approval=earlier,
                            message=_replay_message(earlier))

    context = getattr(agent, "_current_context", None)
    task_id = _task_id_of(context, session_id)
    task = store.get_task(task_id) if task_id else None
    if task is not None:
        origin = task.get("origin") or {}
    else:
        from agent.task.origin import origin_from_context

        origin = origin_from_context(context)

    from agent.task.notify import action_summary, notify_approval_pending

    approval = store.create_approval(
        kind=st.KIND_ACTION,
        task_id=task_id if task else None,
        agent_id=agent_id or (task or {}).get("agent_id", ""),
        session_id=session_id,
        origin=origin,
        tool_name=tool_name,
        tool_args=arguments if isinstance(arguments, dict) else {"value": arguments},
        rule_id=rule.get("id", ""),
        label=label,
        summary=action_summary(tool_name, arguments),
    )
    if approval.pop("is_new", False):
        try:
            notify_approval_pending(approval, task)
        except Exception as e:
            logger.warning(f"[Task] Approval notice failed: {e}")
    logger.info(f"[Task] Tool {tool_name} parked for approval #{approval['id']} ({label})")
    return GateDecision(
        action="ask", rule=rule, approval=approval,
        message=i18n.t(
            f"此操作需要用户审批（#{approval['id']}：{label}），尚未执行。"
            "请先完成不依赖它的步骤，然后结束本轮，并简要说明在等待哪一项审批。",
            f"This action needs the user's approval (#{approval['id']}: {label}) and has NOT run. "
            "Finish whatever does not depend on it, then end this turn and briefly say "
            "which approval you are waiting for.",
        ),
    )


def _task_id_of(context, session_id: str) -> Optional[int]:
    if context is not None:
        try:
            if context.get("is_task") and context.get("task_id"):
                return int(context.get("task_id"))
        except (TypeError, ValueError):
            pass
    return st.task_id_from_session(session_id)


def _replay_message(approval: dict) -> str:
    aid = approval["id"]
    if approval.get("status") == st.APPROVED:
        return i18n.t(
            f"该操作已在审批 #{aid} 通过后执行过，不要重复执行。执行结果：\n{approval.get('exec_result') or ''}",
            f"This action already ran after approval #{aid}; do not run it again. "
            f"Result:\n{approval.get('exec_result') or ''}",
        )
    note = approval.get("decision_note") or i18n.t("无", "none")
    return i18n.t(
        f"该操作已在审批 #{aid} 中被用户驳回（意见：{note}），不要再执行，请换一种方式。",
        f"The user rejected this action in approval #{aid} (note: {note}). "
        "Do not run it; take another approach.",
    )


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

class DecisionError(Exception):
    pass


def _get_bridge():
    from agent.task.runner import _get_bridge as runner_bridge

    return runner_bridge()


def _execute_saved_call(approval: dict, tool_args: dict) -> str:
    """Run the approved call on the session's own Agent and return its output.

    Goes through the session's permission mode like any other call: approval
    adds consent for this action, it does not lift the session's boundary.
    """
    from common.runtime_identity import identity_scope

    tool_name = approval.get("tool_name") or ""
    agent_bridge = _get_bridge()
    agent_id = approval.get("agent_id") or None
    session_id = approval.get("session_id") or None
    with identity_scope(agent_id=agent_id):
        agent = agent_bridge.get_agent(session_id=session_id, agent_id=agent_id)
        if agent is None:
            raise DecisionError("agent unavailable")
        tool = next((t for t in agent.tools if t.name == tool_name), None)
        if tool is None:
            raise DecisionError(f"tool not found: {tool_name}")
        try:
            from agent.permission import FULL_ACCESS, check_tool_call

            mode = agent.effective_permission_mode()
            if mode != FULL_ACCESS:
                verdict = check_tool_call(
                    mode, tool_name, tool_args, cwd=agent.effective_cwd(),
                    write_roots=agent.write_roots(), protected_paths=agent.protected_paths(),
                )
                if not verdict.allowed:
                    return f"Error: {verdict.reason}"
        except Exception as e:
            logger.debug(f"[Task] Permission check skipped for approved call: {e}")
        tool.model = agent.model
        tool.context = agent
        result = tool.execute_tool(tool_args)
    body = result.result
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False)
    text = str(body or "")
    if result.status != "success":
        text = f"Error: {text}"
    if len(text) > EXEC_RESULT_LIMIT:
        text = text[:EXEC_RESULT_LIMIT] + "…"
    return text


def decide(
    approval_id: int,
    decision: str,
    note: str = "",
    tool_args: Optional[dict] = None,
    always_auto: bool = False,
    via: str = "web",
) -> Dict[str, Any]:
    """Settle one approval and set its conversation moving again.

    Returns ``{"approval": ..., "resume": {...} | None}``; ``resume`` names a
    Web conversation turn the caller can follow live.
    """
    store = st.get_task_store()
    approval = store.get_approval(approval_id)
    if approval is None:
        raise DecisionError("approval not found")
    if approval["status"] != st.PENDING:
        raise DecisionError("approval already settled")
    approve = decision == "approve"
    status = st.APPROVED if approve else st.REJECTED
    edited = tool_args if (approve and isinstance(tool_args, dict)) else None

    if not store.decide_approval(approval_id, status, note=note, via=via, tool_args=edited):
        raise DecisionError("approval already settled")
    approval = store.get_approval(approval_id)
    logger.info(f"[Task] Approval #{approval_id} {status} via {via}")

    if approval["kind"] == st.KIND_ACCEPT:
        _settle_accept(approval, approve, note)
        return {"approval": approval, "resume": None}

    if approve:
        try:
            output = _execute_saved_call(approval, approval.get("tool_args") or {})
        except Exception as e:
            output = f"Error: {e}"
        store.set_exec_result(approval_id, output)
        approval["exec_result"] = output
        if always_auto and approval.get("rule_id"):
            try:
                disable_rule(approval["rule_id"])
            except Exception as e:
                logger.warning(f"[Task] Could not switch rule off: {e}")
        message = i18n.t(
            f"[审批结果] 审批 #{approval_id} 已通过，工具 {approval['tool_name']} 已由系统执行"
            + (f"（用户修改了参数：{json.dumps(edited, ensure_ascii=False)}）" if edited else "")
            + f"，结果：\n{output}\n\n请继续完成任务，不要重复执行该操作。",
            f"[Approval result] Approval #{approval_id} was granted and {approval['tool_name']} "
            "has been run by the system"
            + (f" (with arguments edited by the user: {json.dumps(edited, ensure_ascii=False)})" if edited else "")
            + f". Result:\n{output}\n\nContinue the task; do not run that action again.",
        )
        display = i18n.t(f"已通过审批 #{approval_id}：{approval.get('label')}",
                         f"Approved #{approval_id}: {approval.get('label')}")
    else:
        reason = note or i18n.t("（未填写）", "(none given)")
        message = i18n.t(
            f"[审批结果] 审批 #{approval_id} 被驳回，该操作未执行。用户意见：{reason}\n"
            "请据此调整方案，不要再执行原操作。",
            f"[Approval result] Approval #{approval_id} was rejected and the action did not run. "
            f"User's note: {reason}\nAdjust your plan accordingly and do not attempt that action again.",
        )
        display = i18n.t(f"已驳回审批 #{approval_id}" + (f"：{note}" if note else ""),
                         f"Rejected #{approval_id}" + (f": {note}" if note else ""))

    resume = _resume(approval, message, display)
    return {"approval": approval, "resume": resume}


def _resume(approval: dict, message: str, display: str) -> Optional[Dict[str, Any]]:
    """Continue the conversation the approval interrupted."""
    store = st.get_task_store()
    task_id = approval.get("task_id")
    if task_id:
        store.append_pending_input(task_id, message, display)
        task = store.get_task(task_id)
        if task is None or task["status"] in st.FINISHED_STATUSES:
            return None
        # A task still running picks the message up when its turn ends; a
        # waiting one goes back in the queue once nothing else is pending.
        if task["status"] == st.WAITING and not store.pending_for_task(task_id):
            if store.update_task(task_id, expect_status=[st.WAITING], status=st.QUEUED, wait_type=""):
                from agent.task.runner import wake_runner

                wake_runner()
        return None

    session_id = approval.get("session_id")
    origin = approval.get("origin") or {}
    if not session_id:
        return None
    channel_type = origin.get("channel_type") or ""
    agent_id = approval.get("agent_id") or origin.get("agent_id") or ""
    if channel_type == "web":
        try:
            from agent.task.origin import serving_web_channel

            web = serving_web_channel()
            request_id = web.start_server_turn(session_id, agent_id, message, display) if web else ""
            if request_id:
                return {"session_id": session_id, "agent_id": agent_id,
                        "request_id": request_id, "display": display}
        except Exception as e:
            logger.warning(f"[Task] Could not resume web session {session_id}: {e}")
        return None
    threading.Thread(
        target=_resume_im_session, args=(origin, session_id, agent_id, message),
        daemon=True, name="approval-resume",
    ).start()
    return None


def _resume_im_session(origin: dict, session_id: str, agent_id: str, message: str) -> None:
    from agent.task.origin import delivery_context, send_to_origin
    from common.runtime_identity import identity_scope

    try:
        context = delivery_context(origin, message)
        context["session_id"] = session_id
        if agent_id:
            context["agent_id"] = agent_id
        with identity_scope(agent_id=agent_id or None):
            reply = _get_bridge().agent_reply(message, context=context)
        if reply and reply.content:
            send_to_origin(origin, reply)
    except Exception as e:
        logger.error(f"[Task] Resuming session {session_id} after approval failed: {e}")


def _settle_accept(approval: dict, approve: bool, note: str) -> None:
    from agent.task.runner import deliver_result, wake_runner

    store = st.get_task_store()
    task_id = approval.get("task_id")
    task = store.get_task(task_id) if task_id else None
    if task is None:
        return
    if approve:
        if store.update_task(task_id, expect_status=[st.WAITING], status=st.DONE,
                             wait_type="", finished_at=_now()):
            deliver_result(store.get_task(task_id))
        return
    feedback = note or i18n.t("（未填写具体意见）", "(no specific feedback)")
    store.append_pending_input(task_id, i18n.t(
        f"[验收意见] 用户没有通过本次结果，请按以下意见修改后重新给出完整结果：\n{feedback}",
        f"[Review feedback] The user did not accept this result. Revise it per the feedback "
        f"below and give the complete result again:\n{feedback}",
    ), i18n.t(f"返工：{note}" if note else "返工", f"Rework: {note}" if note else "Rework"))
    if store.update_task(task_id, expect_status=[st.WAITING], status=st.QUEUED, wait_type=""):
        wake_runner()


def _now() -> float:
    import time

    return time.time()
