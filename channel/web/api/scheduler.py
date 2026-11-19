"""The scheduler view's endpoints: /api/scheduler/*.

Scheduled tasks and their run records -- create, edit, toggle, delete, run
now -- plus the two lookups the edit dialog needs: which channel instances a
task can be delivered to, and who can receive it.

One handler per route, as web.py wants. They are together because they all
talk to the same task store, which they reach through _global_task_store().
"""

import json

import web

from channel.web.core._common import _request_agent_id, _require_auth
from common.log import logger
from config import conf


# `tool_call` / `skill_call` would run a tool on a timer without the agent's
# permission check, so neither route may produce them.
_ALLOWED_ACTION_TYPES = ("send_message", "agent_task")

# Recorded when an Agent creates the task and bound what its runs may do, so an
# edit must not rewrite them.
_PROTECTED_ACTION_FIELDS = ("origin_session_id", "origin_agent_id", "permission_mode")


def _resolve_instance_agent_id(instance_id: str) -> str:
    """The Agent a channel instance is currently bound to, or "" for none.

    Thin alias over the scheduler's resolver so there is one implementation of
    "which Agent owns this instance" shared by task execution, the task list,
    and task creation. A legacy single-instance channel (instance_id ==
    channel_type) has no explicit binding and resolves to "" -> default Agent.
    """
    from agent.tools.scheduler.integration import _resolve_instance_agent_id as _resolve
    return _resolve(instance_id)


def _global_task_store():
    """The one global task store the console reads and writes.

    All Agents' tasks live in a single file now (each task carries its own
    ``agent_id``), so handlers no longer resolve a per-Agent workspace path.
    """
    from agent.tools.scheduler.integration import get_task_store
    return get_task_store()


class SchedulerHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(agent_id='')
            requested = _request_agent_id(params)

            store = _global_task_store()
            if store is None:
                return json.dumps({"status": "success", "tasks": []}, ensure_ascii=False)

            # An explicit agent_id scopes the list to that Agent; without it the
            # console shows the whole team's schedule.
            tasks = store.list_tasks(agent_id=requested or None)
            # Stamp each task with its *effective* owner so the card/owner-chip
            # always matches what actually runs. For an IM task that is the
            # delivery instance's current binding (a channel re-bind moves the
            # owner with zero data migration); for Web / unbound tasks it is the
            # stored id, defaulting so the client never sees a blank owner it
            # uses to route mutations.
            from agent.tools.scheduler.integration import effective_task_agent_id
            try:
                from agent.registry import get_agent_registry
                default_id = get_agent_registry().default_agent_id
            except Exception:
                default_id = ""
            for task in tasks:
                task["agent_id"] = effective_task_agent_id(task) or default_id
            return json.dumps({"status": "success", "tasks": tasks}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerRunsHandler:
    """Execution history for scheduled tasks.

    Reads the same global ``runs`` ledger every scheduled execution writes to
    (``task_source='scheduler'``) rather than a side-car store, so history JOINs
    cleanly with native turns and needs no extra file. An explicit ``agent_id``
    scopes the list to one Agent; without it the console shows the whole team's
    history. An optional ``task_id`` narrows to a single task's runs.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(agent_id='', task_id='', limit='100', since='', offset='0')
            requested = _request_agent_id(params)
            task_id = (getattr(params, 'task_id', '') or '').strip()
            try:
                limit = max(1, min(500, int(params.limit)))
            except (TypeError, ValueError):
                limit = 100
            # ``offset`` pages the history list ("load more"). Cross-session poll
            # callers omit it (default 0).
            try:
                offset = max(0, int(getattr(params, 'offset', '0') or 0))
            except (TypeError, ValueError):
                offset = 0
            # ``since`` (epoch seconds) powers the client's cross-session
            # scheduler poll: return only executions started after the last one
            # it saw, so a background window/tab can surface a notification for a
            # task that fired in a session the user isn't currently viewing.
            since_raw = (getattr(params, 'since', '') or '').strip()
            try:
                since = int(since_raw) if since_raw else None
            except (TypeError, ValueError):
                since = None

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            if store is None:
                return json.dumps({"status": "success", "runs": []}, ensure_ascii=False)

            runs = store.list_runs(
                task_source="scheduler",
                task_id=task_id or None,
                agent_id=requested,  # None -> whole team; '' -> default Agent
                since=since,
                limit=limit,
                offset=offset,
            )
            # Flatten the light extras index onto each row so the client needs no
            # knowledge of the sidecar shape.
            for run in runs:
                extras = run.pop("extras", {}) or {}
                run["task_name"] = extras.get("task_name", "")
                run["action_type"] = extras.get("action_type", "")
                run["channel_type"] = extras.get("channel_type", "")
                run["instance_id"] = extras.get("instance_id", "")
                run["trigger"] = extras.get("trigger", "")
                run["output_preview"] = extras.get("output_preview", "")
            return json.dumps({"status": "success", "runs": runs}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler runs API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerRunDetailHandler:
    """One execution's full detail for the history detail dialog.

    The list view shows the short ``output_preview`` kept on the run row; opening
    a record fetches the full delivered body by joining back to the receiver's
    session (best-effort — see ``ConversationStore.get_run_detail``). Falls back
    to the preview when the session copy was pruned or never injected.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(run_id='')
            run_id = (getattr(params, 'run_id', '') or '').strip()
            if not run_id:
                return json.dumps({"status": "error", "message": "run_id required"})

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            if store is None:
                return json.dumps({"status": "error", "message": "store unavailable"})

            detail = store.get_run_detail(run_id)
            if detail is None:
                return json.dumps({"status": "error", "message": "run not found"})
            return json.dumps({"status": "success", "run": detail}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler run detail API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerRunDeleteHandler:
    """Delete a single execution-history record from the runs ledger.

    Removes only the ledger row (the list item); the delivered message kept in
    the session history is untouched. Accepts run_id in the JSON body.
    """

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data()) if web.data() else {}
            run_id = (body.get("run_id") or "").strip()
            if not run_id:
                return json.dumps({"status": "error", "message": "run_id required"})

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            if store is None:
                return json.dumps({"status": "error", "message": "store unavailable"})

            deleted = store.delete_run(run_id)
            if not deleted:
                return json.dumps({"status": "error", "message": "run not found"})
            return json.dumps({"status": "success"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler run delete API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerRunHandler:
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            agent_id = _request_agent_id(body)
            task_id = body.get("task_id")
            if not task_id:
                return json.dumps({"status": "error", "message": "task_id required"})

            from agent.tools.scheduler.integration import get_scheduler_service
            service = get_scheduler_service(agent_id=agent_id)
            if service is None:
                return json.dumps({
                    "status": "error",
                    "message": "Scheduler service is not running",
                })

            service.run_task_now(task_id)
            return json.dumps({
                "status": "success",
                "message": f"Task '{task_id}' queued for immediate execution",
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler manual run error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerToggleHandler:
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            task_id = body.get("task_id")
            enabled = body.get("enabled", True)
            if not task_id:
                return json.dumps({"status": "error", "message": "task_id required"})
            store = _global_task_store()
            if store is None:
                return json.dumps({"status": "error", "message": "Scheduler store unavailable"})
            task = store.get_task(task_id)
            if not task:
                return json.dumps(
                    {"status": "error", "message": f"Task '{task_id}' not found"}
                )
            store.enable_task(task_id, enabled)
            return json.dumps(
                {"status": "success", "task": store.get_task(task_id)},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler toggle error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerUpdateHandler:
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            task_id = body.get("task_id")
            if not task_id:
                return json.dumps({"status": "error", "message": "task_id required"})
            
            from agent.tools.scheduler.scheduler_service import SchedulerService
            from datetime import datetime
            store = _global_task_store()
            if store is None:
                return json.dumps({"status": "error", "message": "Scheduler store unavailable"})

            # Get original task (single query to avoid repeated I/O)
            original_task = store.get_task(task_id)
            if not original_task:
                return json.dumps({"status": "error", "message": f"Task '{task_id}' not found"})
            
            # Build updates dict
            updates = {}
            if "name" in body:
                updates["name"] = body["name"]
            if "enabled" in body:
                updates["enabled"] = body["enabled"]
            
            # Update schedule
            if "schedule" in body:
                schedule_patch = body["schedule"]
                if not isinstance(schedule_patch, dict) or not schedule_patch.get("type"):
                    return json.dumps({
                        "status": "error",
                        "message": "schedule must be an object with a type"
                    }, ensure_ascii=False)
                updates["schedule"] = schedule_patch
                # If schedule config changed, recalculate next_run_at
                # Build merged temp task data for calculation (without modifying the original object)
                merged = dict(original_task)
                merged.update(updates)
                if "action" in body:
                    merged["action"] = body["action"]
                temp_service = SchedulerService(store, lambda t: None)
                next_run = temp_service._calculate_next_run(merged, datetime.now())
                if next_run:
                    updates["next_run_at"] = next_run.isoformat()
                else:
                    # Cannot calculate next run time, schedule config may be invalid
                    return json.dumps({
                        "status": "error", 
                        "message": "Cannot calculate next run time. Please check the schedule config (e.g., cron expression format, or whether the one-time task time has already passed)."
                    }, ensure_ascii=False)
            
            # Update action
            if "action" in body:
                # Get the task's original channel_type
                original_action = original_task.get("action", {})
                if not isinstance(original_action, dict):
                    original_action = {}
                action_patch = body["action"]
                if not isinstance(action_patch, dict):
                    return json.dumps({
                        "status": "error",
                        "message": "Action must be an object."
                    }, ensure_ascii=False)

                # The Web editor only exposes a subset of action fields. Merge
                # that patch into the stored action so scheduler metadata such
                # as notify_session_id, silent, and channel-specific delivery
                # fields survive unrelated edits.
                action = dict(original_action)
                action.update({
                    k: v for k, v in action_patch.items()
                    if k not in _PROTECTED_ACTION_FIELDS
                })
                action_type = action.get("type")
                if action_type not in _ALLOWED_ACTION_TYPES:
                    return json.dumps({
                        "status": "error",
                        "message": "unsupported action type",
                    }, ensure_ascii=False)
                if action_type == "send_message":
                    action.pop("task_description", None)
                    action.pop("silent", None)
                elif action_type == "agent_task":
                    action.pop("content", None)

                old_channel = original_action.get("channel_type", "web")
                channel_type = action.get("channel_type") or old_channel
                action["channel_type"] = channel_type

                if not action.get("receiver"):
                    return json.dumps({
                        "status": "error",
                        "message": "Receiver is required. Please create a new task through the chat interface."
                    }, ensure_ascii=False)

                # Web tasks target a chat session, which is not a switchable
                # delivery identity — freeze channel/receiver for them.
                if old_channel == "web" or channel_type == "web":
                    if old_channel != channel_type:
                        return json.dumps({
                            "status": "error",
                            "message": f"Cannot change channel type from '{old_channel}' to '{channel_type}'.",
                        }, ensure_ascii=False)
                else:
                    # IM task: the editor lets the user re-point it at another
                    # channel instance / recipient. Only allow a target that is
                    # in the trusted recipient directory, and take its identity
                    # from the store rather than trusting the request body — the
                    # same rule the create endpoint enforces. This also keeps an
                    # app-scoped id (a Feishu open_id) bound to the instance that
                    # actually owns it.
                    new_instance = (action.get("instance_id") or channel_type).strip()
                    new_receiver = action.get("receiver")
                    repointed = (
                        channel_type != old_channel
                        or new_instance != (original_action.get("instance_id") or old_channel)
                        or new_receiver != original_action.get("receiver")
                    )
                    from agent.tools.scheduler.integration import get_recipient_store
                    target = get_recipient_store().get(new_instance, new_receiver)
                    if repointed and not target:
                        return json.dumps({
                            "status": "error",
                            "message": "recipient is not in the trusted directory",
                        }, ensure_ascii=False)
                    # The delivery identity (notify_session_id decides where output is written)
                    # never comes from the request body: re-derive it from the directory on every
                    # IM edit, falling back to the stored value when the recipient is unknown.
                    source = target or original_action
                    action["channel_type"] = source.get("channel_type") or channel_type
                    action["instance_id"] = source.get("instance_id") or new_instance
                    action["receiver"] = source.get("receiver") or new_receiver
                    action["receiver_name"] = (
                        source.get("name")
                        or source.get("receiver_name")
                        or action["receiver"]
                    )
                    action["is_group"] = bool(
                        source.get("is_group", action.get("is_group", False))
                    )
                    action["notify_session_id"] = (
                        source.get("session_id")
                        or source.get("notify_session_id")
                        or action["receiver"]
                    )
                    # agent_id follows instance_id's live binding, so it needs no update here.
                updates["action"] = action
                
                # If schedule was not updated but action was, ensure next_run_at exists
                if "schedule" not in body and "next_run_at" not in original_task:
                    merged = dict(original_task)
                    merged.update(updates)
                    temp_service = SchedulerService(store, lambda t: None)
                    next_run = temp_service._calculate_next_run(merged, datetime.now())
                    if next_run:
                        updates["next_run_at"] = next_run.isoformat()
            
            store.update_task(task_id, updates)
            task = store.get_task(task_id)
            return json.dumps({"status": "success", "task": task}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler update error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerDeleteHandler:
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            task_id = body.get("task_id")
            if not task_id:
                return json.dumps({"status": "error", "message": "task_id required"})
            
            store = _global_task_store()
            if store is None:
                return json.dumps({"status": "error", "message": "Scheduler store unavailable"})
            store.delete_task(task_id)
            return json.dumps({"status": "success"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler delete error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerInstancesHandler:
    """List channel instances that can be a scheduled-task delivery target.

    The task-create flow picks an instance first, then a recipient within it.
    This returns every external IM instance (web/unknown excluded, as web is not
    a stable delivery target), each with a human-friendly name and how many
    trusted recipients it currently has, so the console can show all instances
    and note the empty ones rather than hiding them.

    Legacy single-instance installs surface here too: each legacy channel type
    resolves to one instance whose id equals the type, so an old setup gets one
    entry per configured channel with no config change.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.scheduler.integration import get_recipient_store
            from channel.channel_instances import (
                resolve_channel_instances,
                _CHANNEL_TYPE_LABELS,
            )
            from agent import team

            # Count recipients per instance so the picker can flag empty ones.
            counts = {}
            for r in get_recipient_store().list():
                iid = r.get("instance_id") or r.get("channel_type") or ""
                counts[iid] = counts.get(iid, 0) + 1

            resolved = team.resolve(conf())
            instances = []
            seen = set()
            for inst in resolve_channel_instances(resolved):
                if inst.channel_type in ("web", "unknown"):
                    continue
                if inst.instance_id in seen:
                    continue
                seen.add(inst.instance_id)
                creds = inst.credentials or {}
                # Prefer the user label; then a credential-carried bot name; then
                # the type's friendly label (so a legacy install without a name
                # reads "微信" not "weixin"); finally the raw id.
                friendly = (
                    inst.name
                    or creds.get("feishu_bot_name")
                    or creds.get("wecom_bot_id")
                    or _CHANNEL_TYPE_LABELS.get(inst.channel_type)
                    or inst.instance_id
                )
                instances.append({
                    "instance_id": inst.instance_id,
                    "channel_type": inst.channel_type,
                    "name": friendly,
                    # Friendly channel-type label (e.g. "微信"), shown on the
                    # right of the picker since the left is the instance name.
                    "channel_label": _CHANNEL_TYPE_LABELS.get(inst.channel_type, inst.channel_type),
                    "agent_id": inst.agent_id or "",
                    "recipient_count": counts.get(inst.instance_id, 0),
                })
            return json.dumps({"status": "success", "instances": instances}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler instances error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerRecipientsHandler:
    """List the trusted cross-channel recipients learned from inbound messages.

    These are people/groups who have already contacted the Agent on an IM
    channel (feishu / wecom_bot / dingtalk / weixin / ...). The Web console uses
    this directory to let a user hand-create a scheduled task that delivers to
    someone on another channel, instead of guessing raw receiver ids.

    Web sessions are intentionally excluded from the directory (they are
    ephemeral and not stable identities), so this endpoint only ever returns
    external-channel recipients.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.scheduler.integration import get_recipient_store

            # The directory is shared across Agents, so it is one read. Each entry
            # already carries instance_id (the exact channel login that saw the
            # person); we enrich it with a human-friendly instance label so the
            # picker reads as "instance · name". The owning Agent is derived at
            # create time from the instance, so it is not needed here.
            recipients = get_recipient_store().list()
            instance_meta = self._instance_meta()
            for item in recipients:
                inst_id = item.get("instance_id") or item.get("channel_type") or ""
                meta = instance_meta.get(inst_id)
                item["instance_name"] = (meta or {}).get("name") or inst_id
            return json.dumps({"status": "success", "recipients": recipients}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler recipients error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    @staticmethod
    def _instance_meta():
        """Map instance_id -> {name} for every configured channel instance, so a
        recipient can be shown by a readable channel label rather than a raw id.
        Best-effort: a missing map just falls back to the id."""
        meta = {}
        try:
            from channel.channel_instances import resolve_channel_instances
            from agent import team
            resolved = team.resolve(conf())
            for inst in resolve_channel_instances(resolved):
                # Prefer the user-set label; then a bot name the channel carries;
                # else the instance id, which at least names the type.
                creds = inst.credentials or {}
                friendly = (
                    inst.name
                    or creds.get("feishu_bot_name")
                    or creds.get("wecom_bot_id")
                    or inst.instance_id
                )
                meta[inst.instance_id] = {"name": friendly}
        except Exception as e:
            logger.debug(f"[WebChannel] Instance meta unavailable: {e}")
        return meta


class SchedulerCreateHandler:
    """Hand-create a scheduled task from the Web console.

    The chat-driven path (SchedulerTool) remains the way to create a task that
    delivers back to the current conversation. This endpoint exists for the
    "actively reach someone else" case: the user picks a trusted recipient and
    the task is stored to deliver on that recipient's channel.

    The recipient is identified by ``instance_id`` (the specific channel instance
    that saw them), not just a channel type: two instances of one channel type
    have separate logins and receiver id spaces, and delivery must go back out
    through the exact instance. The owning Agent is *derived* from that instance's
    binding rather than chosen separately, since a channel instance already binds
    to one Agent. A legacy single-instance channel has ``instance_id ==
    channel_type``, so an old client that only sends a channel type still works.

    Cross-channel delivery is only allowed to a recipient already present in the
    trusted directory; an arbitrary receiver id is rejected. The recipient's
    stable identity (receiver_name / is_group / session_id) is filled from the
    directory rather than trusted from the request body.
    """

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            import uuid
            from datetime import datetime
            from agent.tools.scheduler.scheduler_service import SchedulerService
            from agent.tools.scheduler.integration import get_recipient_store

            body = json.loads(web.data() or b"{}")

            name = (body.get("name") or "").strip()
            if not name:
                return json.dumps({"status": "error", "message": "name is required"})

            schedule = body.get("schedule")
            if not isinstance(schedule, dict) or not schedule.get("type"):
                return json.dumps({"status": "error", "message": "schedule is required"})

            action_in = body.get("action")
            if not isinstance(action_in, dict):
                return json.dumps({"status": "error", "message": "action is required"})

            action_type = action_in.get("type")
            if action_type not in _ALLOWED_ACTION_TYPES:
                return json.dumps({"status": "error", "message": "unsupported action type"})

            channel_type = (action_in.get("channel_type") or "").strip()
            receiver = (action_in.get("receiver") or "").strip()
            # instance_id identifies the exact channel login; fall back to the
            # channel type for a legacy single-instance channel / older client.
            instance_id = (action_in.get("instance_id") or "").strip() or channel_type
            if not channel_type or not receiver:
                return json.dumps({"status": "error", "message": "channel_type and receiver are required"})
            if channel_type in ("web", "unknown"):
                # Web sessions are ephemeral and not a stable delivery target;
                # the console only creates tasks for external-channel recipients.
                return json.dumps({"status": "error", "message": "web is not a valid cross-channel recipient"})

            content = (action_in.get("content") or action_in.get("task_description") or "").strip()
            if not content:
                return json.dumps({"status": "error", "message": "content is required"})

            # The receiver must be in the shared trusted directory; identity
            # fields are taken from the store, never trusted from the client.
            target = get_recipient_store().get(instance_id, receiver)
            if not target:
                return json.dumps({
                    "status": "error",
                    "message": "recipient is not in the trusted directory",
                })

            # Record the current owner as a hint only. For an IM task the true
            # owner is derived at run time from the delivery instance's binding
            # (see effective_task_agent_id), so re-binding the channel moves the
            # task with no rewrite; this stored value is just a fallback for when
            # the instance later has no explicit binding.
            agent_id = _resolve_instance_agent_id(target.get("instance_id") or instance_id)

            action = {
                "type": action_type,
                "receiver": target["receiver"],
                "receiver_name": target.get("name") or target["receiver"],
                "is_group": bool(target.get("is_group", False)),
                "channel_type": target["channel_type"],
                "instance_id": target.get("instance_id") or instance_id,
                "notify_session_id": target.get("session_id") or target["receiver"],
            }
            if action_type == "send_message":
                action["content"] = content
            else:
                action["task_description"] = content
                if action_in.get("silent"):
                    action["silent"] = True

            task_data = {
                "id": str(uuid.uuid4())[:8],
                "name": name,
                "agent_id": agent_id,
                "enabled": bool(body.get("enabled", True)),
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "schedule": schedule,
                "action": action,
            }

            store = _global_task_store()
            if store is None:
                return json.dumps({"status": "error", "message": "Scheduler store unavailable"})
            temp_service = SchedulerService(store, lambda t: None)
            next_run = temp_service._calculate_next_run(task_data, datetime.now())
            if not next_run:
                return json.dumps({
                    "status": "error",
                    "message": "Cannot calculate next run time. Please check the schedule (cron format, or a one-time time already in the past).",
                }, ensure_ascii=False)
            task_data["next_run_at"] = next_run.isoformat()

            store.add_task(task_data)
            return json.dumps({"status": "success", "task": task_data}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler create error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
