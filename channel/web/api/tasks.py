"""The task board's endpoints: /api/tasks/* and /api/approvals/*.

Background tasks (list, create, cancel, retry, delete, reply), the approvals they and
chat turns are waiting on, the feature's settings, and a light summary the
console polls for its bell. Every route answers even with tasks switched off,
so the console can tell "off" from "broken".
"""

import json
import time

import web

from channel.web.core._common import _request_agent_id, _require_auth
from common.log import logger

_RESULT_PREVIEW = 240


def _json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _ok(**fields) -> str:
    return _json({"status": "success", **fields})


def _error(message: str) -> str:
    return _json({"status": "error", "message": message})


def _body() -> dict:
    try:
        data = json.loads(web.data() or b"{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _default_agent_id() -> str:
    try:
        from agent.registry import get_agent_registry

        return get_agent_registry().default_agent_id
    except Exception:
        return ""


def _task_card(task: dict) -> dict:
    """A task as the board shows it: no transcript, a short result."""
    card = dict(task)
    origin = card.pop("origin", None) or {}
    card["origin_channel"] = origin.get("channel_type") or ""
    card["agent_id"] = card.get("agent_id") or _default_agent_id()
    result = card.get("result") or ""
    card["result_preview"] = " ".join(result.split())[:_RESULT_PREVIEW]
    card.pop("result", None)
    card.pop("pending_input", None)
    card.pop("pending_display", None)
    return card


def _approval_view(approval: dict, titles: dict = None) -> dict:
    view = dict(approval)
    origin = view.pop("origin", None) or {}
    view["origin_channel"] = origin.get("channel_type") or ""
    view["origin_session_id"] = origin.get("session_id") or approval.get("session_id") or ""
    if titles is not None and approval.get("task_id"):
        view["task_title"] = titles.get(approval["task_id"], "")
    return view


def _settings_view() -> dict:
    from agent.task.settings import task_settings

    return task_settings()


class TasksHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task.settings import is_enabled
            from agent.task.store import get_task_store

            params = web.input(agent_id='', limit='200', status='', source='', offset='0')
            store = get_task_store()
            filters = {
                "statuses": [s for s in str(params.status or "").split(",") if s] or None,
                "agent_id": _request_agent_id(params),
                "source": params.source or None,
            }
            tasks = store.list_tasks(limit=int(params.limit or 200), offset=int(params.offset or 0), **filters)
            return _ok(
                enabled=is_enabled(),
                tasks=[_task_card(t) for t in tasks],
                total=store.count_tasks(**filters),
                counts=store.count_by_status(),
                pending_approvals=store.count_pending(),
            )
        except Exception as e:
            logger.error(f"[WebChannel] Tasks API error: {e}")
            return _error(str(e))

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task import store as st
            from agent.task.runner import create_task
            from agent.task.settings import is_enabled

            if not is_enabled():
                return _error("tasks are disabled")
            data = _body()
            prompt = str(data.get("prompt") or "").strip()
            if not prompt:
                return _error("prompt is required")
            agent_id = _request_agent_id(data) or _default_agent_id()
            notify_level = data.get("notify_level") or "all"
            task = create_task(
                title=str(data.get("title") or "").strip()[:60],
                prompt=prompt,
                agent_id=agent_id,
                source=st.SOURCE_MANUAL,
                origin={"agent_id": agent_id},
                require_accept=bool(data.get("require_accept")),
                notify_level=notify_level if notify_level in st.NOTIFY_LEVELS else "all",
            )
            return _ok(task=_task_card(task))
        except Exception as e:
            logger.error(f"[WebChannel] Task create error: {e}")
            return _error(str(e))


class TaskSettingsHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            return _ok(settings=_settings_view())
        except Exception as e:
            return _error(str(e))

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task.settings import save_task_settings

            data = _body()
            allowed = ("enabled", "max_concurrency", "notify_webhook", "approval_rules")
            updates = {k: data[k] for k in allowed if k in data}
            if not updates:
                return _error("no updates provided")
            settings = save_task_settings(updates)
            if settings.get("enabled"):
                from agent.task.runner import ensure_runner

                ensure_runner()
            return _ok(settings=settings)
        except Exception as e:
            logger.error(f"[WebChannel] Task settings error: {e}")
            return _error(str(e))


class TaskSummaryHandler:
    """What the bell needs: the pending count and anything new since ``since``."""

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task import store as st
            from agent.task.settings import is_enabled

            if not is_enabled():
                return _ok(enabled=False, pending_approvals=0, counts={}, events=[], now=time.time())
            params = web.input(since='0')
            try:
                since = float(params.since or 0)
            except ValueError:
                since = 0.0
            store = st.get_task_store()
            events = []
            if since > 0:
                for appr in store.list_approvals(status=st.PENDING, limit=50):
                    if appr.get("created_at", 0) > since:
                        events.append({
                            "type": "approval", "id": appr["id"], "kind": appr["kind"],
                            "task_id": appr.get("task_id"), "label": appr.get("label") or "",
                            "summary": appr.get("summary") or "",
                        })
                for task in store.list_tasks(statuses=(st.DONE, st.FAILED), limit=30):
                    if (task.get("finished_at") or 0) > since:
                        events.append({
                            "type": "task_" + task["status"], "id": task["id"],
                            "title": task.get("title") or "", "source": task.get("source") or "",
                            "notify_level": task.get("notify_level") or "all",
                            "origin_channel": (task.get("origin") or {}).get("channel_type") or "",
                        })
            return _ok(
                enabled=True,
                pending_approvals=store.count_pending(),
                counts=store.count_by_status(),
                events=events,
                now=time.time(),
            )
        except Exception as e:
            logger.error(f"[WebChannel] Task summary error: {e}")
            return _error(str(e))


class TaskDetailHandler:
    def GET(self, task_id):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task.store import get_task_store

            store = get_task_store()
            task = store.get_task(int(task_id))
            if task is None:
                return _error("task not found")
            approvals = store.list_approvals(task_id=task["id"], limit=100)
            view = _task_card(task)
            view["result"] = task.get("result") or ""
            view["pending_display"] = task.get("pending_display") or ""
            view["origin"] = task.get("origin") or {}
            view["origin"].pop("context_summary", None)
            return _ok(task=view, approvals=[_approval_view(a) for a in reversed(approvals)])
        except Exception as e:
            logger.error(f"[WebChannel] Task detail error: {e}")
            return _error(str(e))


class TaskActionHandler:
    def POST(self, task_id, action):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task import runner

            task_id = int(task_id)
            if action == "cancel":
                ok = runner.cancel_task(task_id)
            elif action == "retry":
                ok = runner.retry_task(task_id)
            elif action == "delete":
                ok = runner.delete_task(task_id)
            elif action == "reply":
                mode = runner.reply_to_task(task_id, str(_body().get("message") or ""))
                if not mode:
                    return _error("task cannot take a message right now")
                return _ok(mode=mode)
            else:
                return _error("unknown action")
            if not ok:
                return _error("task is not in a state that allows this")
            return _ok()
        except Exception as e:
            logger.error(f"[WebChannel] Task {action} error: {e}")
            return _error(str(e))


class ApprovalsHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task import store as st

            params = web.input(status='pending', limit='100')
            store = st.get_task_store()
            approvals = store.list_approvals(status=params.status or None, limit=int(params.limit or 100))
            task_ids = {a["task_id"] for a in approvals if a.get("task_id")}
            titles = {}
            for tid in task_ids:
                task = store.get_task(tid)
                if task:
                    titles[tid] = task.get("title") or ""
            return _ok(approvals=[_approval_view(a, titles) for a in approvals])
        except Exception as e:
            logger.error(f"[WebChannel] Approvals API error: {e}")
            return _error(str(e))


class ApprovalDecideHandler:
    def POST(self, approval_id):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.task.approval import DecisionError, decide

            data = _body()
            decision = data.get("decision")
            if decision not in ("approve", "reject"):
                return _error("decision must be approve or reject")
            tool_args = data.get("tool_args")
            if tool_args is not None and not isinstance(tool_args, dict):
                return _error("tool_args must be a JSON object")
            try:
                outcome = decide(
                    int(approval_id), decision,
                    note=str(data.get("note") or "").strip(),
                    tool_args=tool_args,
                    always_auto=bool(data.get("always_auto")),
                    via="web",
                )
            except DecisionError as e:
                return _error(str(e))
            return _ok(approval=_approval_view(outcome["approval"]), resume=outcome.get("resume"))
        except Exception as e:
            logger.error(f"[WebChannel] Approval decide error: {e}")
            return _error(str(e))
