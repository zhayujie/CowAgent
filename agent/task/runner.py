"""Background execution of tasks.

A single dispatcher thread moves queued tasks to running, up to
``max_concurrency`` at a time, and runs each on its own thread through the
normal ``agent_reply`` path in an isolated ``task_<id>`` session. Scheduled
runs are outside that limit: they start the moment they fire, as they did
before they ran here. A run ends in
one of: done, failed, waiting for an approval the run asked for, waiting for
the user to accept the result, or straight back in the queue when a decision
arrived while it was still going.

A task found running at startup was cut off by the previous process: it goes
back to the queue with a note to check what was already done before carrying
on. Waiting tasks stay as they are.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Dict, Optional

from common import i18n
from common.log import logger

from agent.task import store as st
from agent.task.settings import is_enabled, task_settings

ORIGIN_CONTEXT_LIMIT = 1500
RESULT_MEMORY_LIMIT = 4000
TASK_CHANNEL_TYPE = "task"
_POLL_SECONDS = 3.0
# Scheduled runs started per dispatcher pass; they are not held back by the
# concurrency limit, this only bounds a single pass.
_SCHEDULED_BATCH = 20


class TaskRunner:
    def __init__(self):
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active: Dict[int, str] = {}  # task id -> cancel token of its run
        self._scheduled: set = set()  # ids in _active that are scheduled runs
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            try:
                store = st.get_task_store()
                for task in store.list_tasks(statuses=[st.RUNNING], limit=1000):
                    store.append_pending_input(task["id"], _recovery_note(task), i18n.t(
                        "↻ 服务重启，继续执行", "↻ Service restarted, carrying on"))
                requeued = store.requeue_interrupted()
                if requeued:
                    logger.info(f"[Task] Re-queued {requeued} task(s) interrupted by the last shutdown")
            except Exception as e:
                logger.warning(f"[Task] Could not re-queue interrupted tasks: {e}")
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="task-runner")
            self._thread.start()
            logger.info("[Task] Runner started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def is_active(self, task_id: int) -> bool:
        with self._lock:
            return task_id in self._active

    def cancel(self, task_id: int) -> None:
        """Stop the run of a task, if it has one in flight."""
        with self._lock:
            token = self._active.get(task_id)
        if not token:
            return
        try:
            from agent.protocol import get_cancel_registry

            get_cancel_registry().cancel_request(token)
        except Exception as e:
            logger.debug(f"[Task] Cancel signal for #{task_id} failed: {e}")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if is_enabled():
                    store = st.get_task_store()
                    for task in store.claim_next(_SCHEDULED_BATCH, scheduled=True):
                        self._launch(task)
                    with self._lock:
                        busy = len(self._active) - len(self._scheduled)
                    free = task_settings()["max_concurrency"] - busy
                    for task in store.claim_next(free, scheduled=False):
                        self._launch(task)
            except Exception as e:
                logger.error(f"[Task] Dispatcher error: {e}")
            self._wake.wait(_POLL_SECONDS)
            self._wake.clear()

    def _launch(self, task: dict) -> None:
        agent_bridge = _get_bridge()
        agent_id = task.get("agent_id") or agent_bridge.agent_registry.default_agent_id
        token = f"task_{task['id']}_{uuid.uuid4().hex[:8]}"
        default_id = agent_bridge.agent_registry.default_agent_id
        cancel_key = agent_bridge._cancel_key(agent_id, token, default_id)
        with self._lock:
            self._active[task["id"]] = cancel_key
            if task.get("source") == st.SOURCE_SCHEDULE:
                self._scheduled.add(task["id"])
        threading.Thread(
            target=self._run, args=(task, agent_id, token), daemon=True,
            name=f"task-{task['id']}",
        ).start()

    def _run(self, task: dict, agent_id: str, token: str) -> None:
        task_id = task["id"]
        store = st.get_task_store()
        try:
            task["pending_input"], task["pending_display"] = store.take_pending_input(task_id)
            prompt = _build_prompt(task)
            logger.info(f"[Task] #{task_id} running (round {task.get('run_count')})")
            reply = _run_agent(task, agent_id, prompt, token)
            self._finish(task_id, reply)
        except Exception as e:
            logger.error(f"[Task] #{task_id} crashed: {e}", exc_info=True)
            self._fail(task_id, str(e))
        finally:
            with self._lock:
                self._active.pop(task_id, None)
                self._scheduled.discard(task_id)
            self._wake.set()

    def _finish(self, task_id: int, reply) -> None:
        store = st.get_task_store()
        task = store.get_task(task_id)
        if task is None or task["status"] != st.RUNNING:
            return  # cancelled or deleted while it ran

        from bridge.reply import ReplyType

        if reply is None or reply.type == ReplyType.ERROR:
            self._fail(task_id, str(getattr(reply, "content", "") or "no reply"))
            return
        content = _reply_text(reply)

        # Something decided while this run was going: run again with it.
        if task.get("pending_input") and not store.pending_for_task(task_id):
            store.update_task(task_id, expect_status=[st.RUNNING], status=st.QUEUED, result=content)
            return
        if store.pending_for_task(task_id):
            store.update_task(task_id, expect_status=[st.RUNNING], status=st.WAITING,
                              wait_type=st.WAIT_APPROVAL, result=content)
            logger.info(f"[Task] #{task_id} waiting for approval")
            return
        if task.get("require_accept"):
            from agent.task.notify import action_summary, notify_accept_pending

            approval = store.create_approval(
                kind=st.KIND_ACCEPT, task_id=task_id, agent_id=task.get("agent_id", ""),
                session_id=task.get("session_id", ""), origin=task.get("origin") or {},
                label=task.get("title") or "", summary=content[:300],
            )
            store.update_task(task_id, expect_status=[st.RUNNING], status=st.WAITING,
                              wait_type=st.WAIT_ACCEPT, result=content)
            if approval.pop("is_new", False):
                notify_accept_pending(approval, store.get_task(task_id), content)
            logger.info(f"[Task] #{task_id} waiting for review (#{approval['id']})")
            return
        if store.update_task(task_id, expect_status=[st.RUNNING], status=st.DONE,
                             wait_type="", result=content, error="", finished_at=time.time()):
            logger.info(f"[Task] #{task_id} done")
            deliver_result(store.get_task(task_id), reply=reply)

    def _fail(self, task_id: int, error: str) -> None:
        store = st.get_task_store()
        if store.update_task(task_id, expect_status=[st.RUNNING], status=st.FAILED,
                             wait_type="", error=error[:2000], finished_at=time.time()):
            store.expire_for_task(task_id)
            task = store.get_task(task_id)
            if task and task.get("source") == st.SOURCE_SCHEDULE:
                _record_schedule_run(task, status="error", error=error)
            try:
                from agent.task.notify import notify_task_failed

                notify_task_failed(task, error)
            except Exception as e:
                logger.warning(f"[Task] Failure notice for #{task_id} failed: {e}")


_bridge_ref = None


def _get_bridge():
    if _bridge_ref is not None:
        return _bridge_ref
    from bridge.bridge import Bridge

    return Bridge().get_agent_bridge()


def _reply_text(reply) -> str:
    """The text of a run's reply; files it produced are listed by path."""
    from bridge.reply import ReplyType

    if reply.type not in (ReplyType.FILE, ReplyType.IMAGE_URL, ReplyType.VIDEO_URL):
        return str(reply.content or "").strip()
    parts = [str(getattr(reply, "text_content", "") or "").strip()]
    for item in [reply] + list(getattr(reply, "extra_replies", None) or []):
        ref = str(item.content or "")
        if ref:
            parts.append(ref[len("file://"):] if ref.startswith("file://") else ref)
    return "\n".join(p for p in parts if p)


def _build_prompt(task: dict) -> str:
    """The message for this round: the brief on the first one, after that
    whatever the user decided in between."""
    pending = (task.get("pending_input") or "").strip()
    if task.get("run_count", 1) > 1 and pending:
        return pending
    if task.get("source") == st.SOURCE_SCHEDULE:
        # Same directive the scheduler uses: a stored description often reads
        # like a rule ("every day at 8 send ...") rather than a job to do now.
        brief = (
            "这是一个定时任务的立即执行请求，当前已到执行时刻。"
            "请直接完成下面描述的任务并产出最终交付内容，"
            "无需复述、确认或讨论任务规则，不要输出任务指令或调试信息。"
            "若执行失败，返回简洁明确的失败说明。"
        )
        parts = [brief, f"任务描述：\n{task.get('prompt') or ''}"]
        if pending:
            parts.append(pending)
        return "\n\n".join(parts)
    brief = i18n.t(
        f"[后台任务 #{task['id']}] {task.get('title') or ''}\n"
        "你正在后台执行用户委托的任务，用户此刻不在线等待。请独立完成，直接产出最终结果"
        "（结果会原样转交给用户），不要向用户提问或等待确认；确实无法完成时，说明原因。",
        f"[Background task #{task['id']}] {task.get('title') or ''}\n"
        "You are running a task the user handed off; they are not waiting online. Work it "
        "through on your own and produce the final result (it is passed to the user as is). "
        "Do not ask the user questions or wait for confirmation; if it cannot be done, say why.",
    )
    context = (task.get("origin") or {}).get("context_summary") or ""
    parts = [brief]
    if context:
        parts.append(i18n.t("发起任务时的对话摘录：\n", "Excerpt of the conversation it came from:\n") + context)
    parts.append(i18n.t("任务内容：\n", "Task:\n") + (task.get("prompt") or ""))
    if pending:
        parts.append(pending)
    return "\n\n".join(parts)


def _recovery_note(task: dict) -> str:
    """The next round's message for a task the last shutdown cut off. Its
    finished steps are in the session, but a first round may have stopped
    before any were stored, so that one carries its brief again."""
    note = i18n.t(
        "服务在执行这个任务时重启了，上一轮只保存了部分进度。继续之前先核对已经做过的事"
        "（文件、已发出的消息、对外的改动），已经完成的对外操作不要重复；然后把任务做完，给出最终结果。",
        "The service restarted while this task was running, so only part of the last round "
        "was saved. Before carrying on, check what is already done (files, messages sent, "
        "external changes) and do not repeat an external action that already completed; "
        "then finish the task and give the final result.",
    )
    if task.get("run_count", 1) > 1:
        return note
    return f"{_build_prompt({**task, 'run_count': 1, 'pending_input': ''})}\n\n{note}"


def _run_agent(task: dict, agent_id: str, prompt: str, token: str):
    from bridge.context import Context, ContextType
    from common.runtime_identity import identity_scope

    session_id = task.get("session_id") or st.task_session_id(task["id"])
    context = Context(ContextType.TEXT, prompt)
    context["session_id"] = session_id
    context["receiver"] = session_id
    context["agent_id"] = agent_id
    context["channel_type"] = TASK_CHANNEL_TYPE
    context["request_id"] = token
    context["is_task"] = True
    context["task_id"] = str(task["id"])
    context["task_source"] = "task"
    if task.get("source") == st.SOURCE_SCHEDULE:
        # Lets the run end with nothing to report, as scheduled runs may.
        context["is_scheduled_task"] = True
    context["display"] = _round_display(task, prompt)
    from agent.task.origin import serving_web_channel

    web = serving_web_channel()
    on_event = None
    if web is not None:
        try:
            on_event = web.open_background_stream(token, session_id, agent_id)
        except Exception as e:
            logger.debug(f"[Task] #{task['id']} runs without a live stream: {e}")
            web = None
    reply = None
    try:
        with identity_scope(agent_id=agent_id):
            reply = _get_bridge().agent_reply(prompt, context=context, on_event=on_event)
        return reply
    finally:
        if web is not None:
            web.close_background_stream(token, _reply_text(reply) if reply is not None else "")


def _round_display(task: dict, prompt: str) -> str:
    """What the transcript shows for this round's message: the brief as the
    user wrote it, then whatever was sent in between."""
    shown = (task.get("pending_display") or "").strip()
    if task.get("run_count", 1) <= 1:
        return "\n\n".join(p for p in ((task.get("prompt") or "").strip(), shown) if p)
    if shown:
        return shown
    first = prompt.strip().splitlines()[0] if prompt.strip() else ""
    return first[:120]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def deliver_result(task: Optional[dict], reply=None) -> None:
    """Hand a finished task's result back to where it came from. ``reply`` is
    the final run's reply when there is one, so a scheduled run can deliver
    its files and images the way the scheduler always has."""
    if not task:
        return
    result = task.get("result") or ""
    origin = task.get("origin") or {}
    try:
        from agent.task.notify import can_quote_reply, done_text, notify_task_done
        from agent.task.origin import is_deliverable, send_text_to_origin

        if task.get("source") == st.SOURCE_SCHEDULE:
            # A follow-up asked for on the board is read there; the schedule's
            # receiver already got this firing's result.
            if not origin.get("follow_up"):
                _deliver_scheduled(task, result, reply)
        else:
            _remember_in_origin(task, result)
            level = task.get("notify_level") or "all"
            if level == "all" and is_deliverable(origin):
                if origin.get("channel_type") == "web":
                    # An open chat shows it live; the stored copy covers the rest.
                    send_text_to_origin(origin, _web_result_text(task, result))
                else:
                    send_text_to_origin(origin, done_text(task, result, quote_hint=can_quote_reply(task)))
        notify_task_done(task, result)
    except Exception as e:
        logger.warning(f"[Task] Delivering result of #{task.get('id')} failed: {e}")


def _web_result_text(task: dict, result: str) -> str:
    from agent.task.notify import done_heading

    return f"{done_heading(task['id'], task.get('title') or '', link=True)}\n\n{result}"


def _remember_in_origin(task: dict, result: str) -> None:
    """Put the result into the conversation that asked for it, so a follow-up
    question there can build on it."""
    origin = task.get("origin") or {}
    session_id = origin.get("session_id")
    if not session_id or not result:
        return
    try:
        remember = getattr(_get_bridge(), "remember_task_output", None)
        if remember:
            remember(
                session_id, task["id"], task.get("title") or "", result,
                channel_type=origin.get("channel_type") or "",
                agent_id=task.get("agent_id") or None,
            )
    except Exception as e:
        logger.warning(f"[Task] Could not write result of #{task['id']} back: {e}")


def _schedule_of(task: dict) -> dict:
    origin = task.get("origin") or {}
    try:
        from agent.tools.scheduler.integration import get_task_store

        sched_store = get_task_store()
        found = sched_store.get_task(task.get("schedule_id")) if sched_store else None
        if found:
            return found
    except Exception:
        pass
    return {
        "id": task.get("schedule_id"), "name": task.get("title"),
        "action": {
            "type": "agent_task", "channel_type": origin.get("channel_type"),
            "receiver": origin.get("receiver"), "notify_session_id": origin.get("session_id"),
            "instance_id": origin.get("instance_id"), "task_description": task.get("prompt"),
        },
    }


def _record_schedule_run(task: dict, status: str, error: str = "", output: str = "",
                         sched_task: Optional[dict] = None) -> str:
    """Log the firing in the scheduler's run history, as the old path did."""
    from agent.tools.scheduler import integration as sched

    sched_task = sched_task or _schedule_of(task)
    trigger = (task.get("origin") or {}).get("trigger") or "scheduled"
    run = sched._record_scheduler_run(sched_task, task.get("agent_id") or "", trigger=trigger)
    if run is None:
        return ""
    run_store, run_id = run
    extras = {"background_task_id": task["id"]}
    output = (output or "").strip()
    if output:
        if len(output) > sched._OUTPUT_PREVIEW_LIMIT:
            output = output[:sched._OUTPUT_PREVIEW_LIMIT].rstrip() + "…"
        extras["output_preview"] = output
    try:
        run_store.finish_run(run_id, status=status, error=error[:500], extras=extras)
    except Exception as e:
        logger.debug(f"[Task] Could not close scheduler run for #{task['id']}: {e}")
    return run_id


def _deliver_scheduled(task: dict, result: str, reply=None) -> None:
    """A scheduled run delivers exactly as it did before tasks existed: the
    reply itself, plus a record in the scheduler's run history."""
    from agent.task.origin import send_text_to_origin, send_to_origin
    from agent.tools.scheduler import integration as sched

    origin = task.get("origin") or {}
    sched_task = _schedule_of(task)
    delivered = False
    if result and not origin.get("silent"):
        delivered = send_to_origin(origin, reply) if reply is not None else send_text_to_origin(origin, result)
    run_id = _record_schedule_run(
        task, status="done" if delivered or not result or origin.get("silent") else "error",
        error="" if delivered or not result or origin.get("silent") else "delivery failed",
        output=result if delivered else "", sched_task=sched_task,
    )
    if delivered:
        sched._remember_delivered_output(
            _get_bridge(), sched_task, origin.get("channel_type") or "",
            reply.content if reply is not None else result,
            task.get("agent_id") or "", run_id=run_id,
        )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

_runner: Optional[TaskRunner] = None
_runner_lock = threading.Lock()


def get_runner() -> TaskRunner:
    global _runner
    if _runner is None:
        with _runner_lock:
            if _runner is None:
                _runner = TaskRunner()
    return _runner


def ensure_runner(agent_bridge=None) -> TaskRunner:
    """Start the runner if it is not going. Pass the bridge when calling from
    its own constructor, before ``Bridge`` can hand it out."""
    global _bridge_ref
    if agent_bridge is not None:
        _bridge_ref = agent_bridge
    runner = get_runner()
    if not runner.running:
        runner.start()
    return runner


def wake_runner() -> None:
    ensure_runner().wake()


def create_task(
    title: str,
    prompt: str,
    agent_id: str = "",
    source: str = st.SOURCE_MANUAL,
    origin: Optional[dict] = None,
    require_accept: bool = False,
    notify_level: str = "all",
    schedule_id: str = "",
    session_id: str = "",
) -> dict:
    title = (title or "").strip() or ((prompt or "").strip().splitlines() or [""])[0][:40]
    task = st.get_task_store().create_task(
        title=title, prompt=prompt, agent_id=agent_id, source=source, origin=origin,
        require_accept=require_accept, notify_level=notify_level, schedule_id=schedule_id,
        session_id=session_id,
    )
    logger.info(f"[Task] #{task['id']} created ({source}): {title}")
    wake_runner()
    return task


def cancel_task(task_id: int) -> bool:
    store = st.get_task_store()
    if not store.update_task(task_id, expect_status=st.ACTIVE_STATUSES,
                             status=st.CANCELLED, wait_type="", finished_at=time.time()):
        return False
    store.expire_for_task(task_id)
    get_runner().cancel(task_id)
    logger.info(f"[Task] #{task_id} cancelled")
    return True


def reply_to_task(task_id: int, message: str) -> Optional[str]:
    """Hand a task more instructions (from its detail view, a quoted notice or
    the conversation's task tool). Returns how it was
    taken: ``steer`` (read by the running round), ``queued`` (read when the
    next round starts), ``rework`` (the result under review is redone) or
    ``reopened`` (a finished task carries on with its full context)."""
    message = (message or "").strip()
    store = st.get_task_store()
    task = store.get_task(task_id)
    if not message or task is None:
        return None
    status = task["status"]
    if status == st.RUNNING:
        try:
            from agent.protocol.steer import SteerStatus

            result = _get_bridge().steer_session(task["session_id"], message, task.get("agent_id") or None)
            if result.status == SteerStatus.ACCEPTED:
                return "steer"
        except Exception as e:
            logger.debug(f"[Task] Steering #{task_id} failed, queueing instead: {e}")
        store.append_pending_input(task_id, message)
        return "queued"
    if status == st.QUEUED:
        store.append_pending_input(task_id, message)
        return "queued"
    if status == st.WAITING and task.get("wait_type") == st.WAIT_ACCEPT:
        from agent.task.approval import DecisionError, decide

        for appr in store.list_approvals(task_id=task_id, status=st.PENDING, limit=5):
            if appr.get("kind") == st.KIND_ACCEPT:
                try:
                    decide(appr["id"], "reject", note=message, via="web")
                    return "rework"
                except DecisionError:
                    break
        return None
    if status == st.WAITING:
        store.append_pending_input(task_id, message)
        return "queued"
    origin = dict(task.get("origin") or {})
    origin["follow_up"] = True
    store.append_pending_input(task_id, message)
    if not store.update_task(task_id, expect_status=st.FINISHED_STATUSES, status=st.QUEUED,
                             wait_type="", error="", finished_at=0, origin=origin):
        return None
    wake_runner()
    logger.info(f"[Task] #{task_id} reopened with a follow-up")
    return "reopened"


def retry_task(task_id: int) -> bool:
    """Run a finished task again from its original brief."""
    store = st.get_task_store()
    task = store.get_task(task_id)
    if task is None or task["status"] not in st.FINISHED_STATUSES:
        return False
    origin = dict(task.get("origin") or {})
    origin.pop("follow_up", None)
    if not store.update_task(task_id, expect_status=st.FINISHED_STATUSES, status=st.QUEUED,
                             wait_type="", error="", result="", pending_input="", pending_display="",
                             run_count=0, finished_at=0, origin=origin):
        return False
    _clear_task_session(task)
    wake_runner()
    return True


def delete_task(task_id: int) -> bool:
    store = st.get_task_store()
    task = store.get_task(task_id)
    if task is None:
        return False
    if task["status"] in st.ACTIVE_STATUSES:
        cancel_task(task_id)
    _clear_task_session(task)
    return store.delete_task(task_id)


def _clear_task_session(task: dict) -> None:
    if not st.task_id_from_session(task.get("session_id") or ""):
        return  # a schedule's shared session outlives any one firing
    agent_bridge = _get_bridge()
    agent_id = task.get("agent_id") or None
    try:
        agent_bridge.clear_session(task.get("session_id"), agent_id=agent_id)
        agent_bridge.get_conversation_store(agent_id).clear_session(task.get("session_id"))
    except Exception as e:
        logger.debug(f"[Task] Could not clear session of #{task.get('id')}: {e}")


def handoff_scheduled_task(sched_task: dict, agent_id: str, trigger: str = "scheduled") -> bool:
    """Turn one firing of an ``agent_task`` schedule into a task, when tasks
    are on. Returns False to leave the scheduler on its old path."""
    if not is_enabled():
        return False
    from agent.task.origin import origin_from_scheduled_action

    action = sched_task.get("action") or {}
    description = action.get("task_description") or ""
    if not description:
        return False
    schedule_id = str(sched_task.get("id") or "")
    store = st.get_task_store()
    if schedule_id and store.count_tasks(statuses=st.ACTIVE_STATUSES, schedule_id=schedule_id):
        # The scheduler never overlapped two runs of one schedule; a firing
        # that lands while the last one is still going is skipped.
        logger.info(f"[Task] Schedule {schedule_id}: previous run still in progress, skipping this firing")
        return True
    origin = origin_from_scheduled_action(action, agent_id)
    origin["trigger"] = trigger
    receiver = action.get("receiver") or ""
    create_task(
        session_id=f"scheduler_{receiver}_{sched_task.get('id')}",
        title=sched_task.get("name") or description[:40],
        prompt=description,
        agent_id=agent_id,
        source=st.SOURCE_SCHEDULE,
        origin=origin,
        notify_level="action_only",
        schedule_id=schedule_id,
    )
    return True


def origin_context_summary(messages, limit: int = ORIGIN_CONTEXT_LIMIT) -> str:
    """The last few text turns of a conversation, newest kept, within ``limit``."""
    lines = []
    for msg in reversed(list(messages or [])[-12:]):
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content or "")
        text = " ".join(text.split())
        if not text or role not in ("user", "assistant"):
            continue
        who = i18n.t("用户", "User") if role == "user" else i18n.t("助手", "Assistant")
        lines.append(f"{who}: {text[:400]}")
        if sum(len(x) for x in lines) > limit:
            break
    summary = "\n".join(reversed(lines))
    return summary[-limit:]
