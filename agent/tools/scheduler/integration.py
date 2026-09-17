"""
Integration module for scheduler with AgentBridge
"""

import os
import threading
from typing import Dict
from config import conf
from common.log import logger
from common.utils import expand_path
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType

# One global scheduler for the whole process. Tasks are no longer sharded per
# Agent workspace; the single store at ``scheduler_file_global()`` holds every
# Agent's tasks, each tagged with its own ``agent_id`` (the Agent it runs as) and
# ``instance_id`` (the channel login it delivers through). One service scans that
# store; before running a task it scopes the runtime identity to the task's
# ``agent_id``. This decouples task ownership from a channel instance's current
# Agent binding: re-binding an instance moves no task data.
_scheduler_service = None
_task_store = None
# The recipient directory is shared across every Agent (state_dir
# .scheduler_recipients_file), a single process-wide instance not one per workspace.
_recipient_store = None
# Module-level lock to guard idempotent initialization across threads
_init_lock = threading.RLock()
# One-shot fold of per-Agent ``scheduler/tasks.json`` files into the global store.
_legacy_stores_migrated = False


def _get_shared_recipient_store():
    """The one recipient directory every Agent reads and writes.

    Lives beside the global tasks.json at ``scheduler/recipients.json``; shared,
    not per Agent, so any Agent's console can target anyone the instance has met.
    """
    global _recipient_store
    if _recipient_store is None:
        with _init_lock:
            if _recipient_store is None:
                from agent.tools.scheduler.recipient_store import RecipientStore
                from common.state_dir import scheduler_recipients_file
                _recipient_store = RecipientStore(str(scheduler_recipients_file()))
    return _recipient_store


def _resolve_workspace(workspace_root: str = None, agent_id: str = None):
    """An explicit workspace wins, then an explicit agent_id, then the routed
    identity. An agent_id that does not resolve raises: falling back to the
    default workspace here would silently file one Agent's tasks under
    another."""
    if workspace_root is not None:
        return os.path.realpath(expand_path(str(workspace_root)))
    from common.runtime_identity import current_identity
    from common.state_dir import state_root

    identity = current_identity()
    if agent_id:
        identity = identity.derive(agent_id=agent_id)
    return str(state_root(identity))


def _migrate_legacy_task_stores(task_store) -> None:
    """Fold per-Agent ``scheduler/tasks.json`` files into the one global store.

    The global file *is* the default Agent's historical path
    (``shared_root/scheduler/tasks.json``), so those tasks stay put — we only
    stamp a missing ``agent_id``. Every other Agent's workspace file is imported
    once (skipping ids that already exist globally) and then renamed
    ``.migrated`` so a later boot does not re-import them.

    Re-binding a channel instance never calls this and never moves a task:
    ownership lives on the task's ``agent_id`` field, not in the file path.
    """
    global _legacy_stores_migrated
    if _legacy_stores_migrated:
        return
    try:
        from agent.registry import get_agent_registry
        from common.state_dir import scheduler_file, scheduler_file_global

        registry = get_agent_registry()
        default_id = registry.default_agent_id
        global_path = os.path.realpath(str(scheduler_file_global()))

        tasks = task_store.load_tasks()
        changed = False

        # Stamp missing owner on tasks already in the global file.
        for task in tasks.values():
            if not (task.get("agent_id") or "").strip():
                task["agent_id"] = default_id
                changed = True

        for profile in registry.list(include_disabled=True):
            legacy_path = os.path.realpath(str(scheduler_file(base=profile.workspace)))
            if legacy_path == global_path:
                continue
            if not os.path.exists(legacy_path):
                continue
            try:
                legacy_store = type(task_store)(legacy_path)
                incoming = legacy_store.load_tasks()
            except Exception as e:
                logger.warning(
                    f"[Scheduler] Skip legacy store {legacy_path}: {e}"
                )
                continue
            imported = 0
            skipped = 0
            for task_id, task in incoming.items():
                if task_id in tasks:
                    skipped += 1
                    continue
                task = dict(task)
                if not (task.get("agent_id") or "").strip():
                    task["agent_id"] = profile.id
                tasks[task_id] = task
                imported += 1
                changed = True
            migrated_path = legacy_path + ".migrated"
            try:
                os.replace(legacy_path, migrated_path)
            except OSError as e:
                logger.warning(
                    f"[Scheduler] Imported {imported} task(s) from {legacy_path} "
                    f"but could not rename it aside: {e}"
                )
            else:
                logger.info(
                    f"[Scheduler] Migrated {imported} task(s) from {legacy_path} "
                    f"into the global store"
                    + (f" (skipped {skipped} duplicate id(s))" if skipped else "")
                )

        if changed:
            task_store.save_tasks(tasks)
        _legacy_stores_migrated = True
    except Exception as e:
        logger.warning(f"[Scheduler] Legacy task-store migration failed: {e}")


def _resolve_instance_agent_id(instance_id: str) -> str:
    """The Agent a channel instance is currently bound to, or "" for none.

    Read live from the channel-instance config (team.json) rather than cached on
    the task, so re-binding an instance to another Agent takes effect on the next
    tick with no data migration. An unbound / legacy single-instance channel
    (instance_id == channel_type, no explicit binding) returns "".
    """
    instance_id = (instance_id or "").strip()
    if not instance_id:
        return ""
    try:
        from channel.channel_instances import get_instance
        from config import conf

        inst = get_instance(conf(), instance_id)
        if inst and (inst.agent_id or "").strip():
            return inst.agent_id.strip()
    except Exception as e:
        logger.debug(
            f"[Scheduler] Could not resolve agent for instance '{instance_id}': {e}"
        )
    return ""


def effective_task_agent_id(task: dict, registry=None, validate: bool = False) -> str:
    """Who a task belongs to *right now*.

    This is the one place that decides ownership so execution and the console
    never disagree. For an IM task the delivery instance's current binding wins
    (re-binding a channel silently moves its tasks); otherwise the stored
    ``agent_id`` is used; falling back to the default Agent.

    ``validate`` gates whether an id must resolve to an *enabled* Agent:
      * execution passes ``validate=True`` so a tick never runs as a removed or
        disabled Agent (it degrades to the default instead);
      * display callers (the list endpoint / ``list_tasks`` bucketing) leave it
        False so a task keeps showing its stored owner even in contexts without
        a live registry (e.g. unit tests) — the id is a label there, not an
        identity to assume.

    ``registry`` is optional; when None it is resolved lazily and, if that
    fails, validation is skipped and the default falls back to "".
    """
    if registry is None:
        try:
            from agent.registry import get_agent_registry
            registry = get_agent_registry()
        except Exception:
            registry = None

    def _take(agent_id: str) -> str:
        agent_id = (agent_id or "").strip()
        if not agent_id:
            return ""
        if not validate or registry is None:
            return agent_id
        try:
            return registry.get(agent_id, require_enabled=True).id
        except Exception:
            return ""

    if isinstance(task, dict):
        action = task.get("action") if isinstance(task.get("action"), dict) else {}
        instance_id = (action.get("instance_id") or "").strip()
        channel_type = (action.get("channel_type") or "").strip()
        # Web targets a chat session, not a bound external instance, so it keeps
        # using the stored agent_id; only external IM instances derive live.
        if instance_id and channel_type not in ("", "web"):
            derived = _take(_resolve_instance_agent_id(instance_id))
            if derived:
                return derived
        stored = _take(task.get("agent_id"))
        if stored:
            return stored
    if registry is not None:
        return registry.default_agent_id
    return ""


def _resolve_task_agent_id(agent_bridge, task: dict) -> str:
    """The Agent a task runs as, resolved against the live registry.

    Thin wrapper over :func:`effective_task_agent_id` that validates (so a tick
    never runs as a removed/disabled Agent) and always yields a concrete Agent
    id (the default when nothing else resolves).
    """
    registry = agent_bridge.agent_registry
    return (
        effective_task_agent_id(task, registry, validate=True)
        or registry.default_agent_id
    )


def init_scheduler(agent_bridge, workspace_root: str = None, agent_id: str = None) -> bool:
    """
    Initialize the one global scheduler service (idempotent).

    Safe to call any number of times and from any Agent: the scheduler is now a
    single process-wide service over one global task store, so the first call
    builds it and every later call (per-Agent warmup, roster reload, a lazy
    first-message init) is a no-op that just returns True. The ``workspace_root``
    / ``agent_id`` arguments are ignored — they only remain so existing per-Agent
    call sites need no change.

    Args:
        agent_bridge: AgentBridge instance

    Returns:
        True if the scheduler is initialized (newly created or already running)
    """
    global _scheduler_service, _task_store

    # Fast path: already running.
    if _scheduler_service is not None and getattr(_scheduler_service, "running", False):
        return True

    with _init_lock:
        if _scheduler_service is not None and getattr(_scheduler_service, "running", False):
            return True

        try:
            from agent.tools.scheduler.task_store import TaskStore
            from agent.tools.scheduler.scheduler_service import SchedulerService
            from common.state_dir import scheduler_file_global

            store_path = str(scheduler_file_global())
            task_store = TaskStore(store_path)
            _task_store = task_store
            _migrate_legacy_task_stores(task_store)
            logger.debug(f"[Scheduler] Global task store initialized: {store_path}")

            _get_shared_recipient_store()

            # Execute callback. Returns True on success, False to retry next tick
            # (e.g. channel not ready just after start). The Agent identity is
            # taken from the task itself (not a closure), so one service runs
            # tasks belonging to any Agent under the right workspace/memory/tools.
            def execute_task_callback(task: dict, trigger: str = "scheduled"):
                from common.runtime_identity import identity_scope

                agent_id = _resolve_task_agent_id(agent_bridge, task)
                try:
                    with identity_scope(agent_id=agent_id):
                        return _run_scheduled_task(task, agent_bridge, agent_id, trigger=trigger)
                except Exception as e:
                    logger.error(f"[Scheduler] Error executing task {task.get('id')}: {e}")
                    return False

            service = SchedulerService(task_store, execute_task_callback)
            service.start()
            _scheduler_service = service

            logger.info(f"[Scheduler] Global service initialized, store={store_path}")
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to initialize scheduler: {e}")
            return False


def _primary_channel_type(raw) -> str:
    """Normalize a task's stored channel_type to a single channel name.

    config.json allows a comma-joined value (e.g. "feishu,dingtalk") that
    app.py splits into several channels at startup. A scheduled task, though,
    delivers to one place, and create_channel() only understands a single type
    — passing the whole "feishu,dingtalk" string lands in its `else: raise`.
    Take the first non-empty entry so a task copied from that config still
    delivers instead of failing every tick.
    """
    if not raw:
        return "unknown"
    first = str(raw).split(",")[0].strip()
    return first or "unknown"


def _is_live_channel_instance(channel) -> bool:
    """True when *channel* is one ChannelManager is actually running.

    Distinguishes a real, started instance (which reflects real login/token
    state) from the bare singleton ``create_channel`` hands back when nothing is
    running. Only for the former does an empty token map mean "not ready"; for
    the latter it means "we can't tell", so callers must not hard-block on it.
    """
    try:
        from common.channel_registry import get_channel_manager
        manager = get_channel_manager()
        if manager is None:
            return False
        for _name, ch in manager.find_channels_by_type(getattr(channel, "channel_type", "")):
            if ch is channel:
                return True
    except Exception:
        return False
    return False


def _channel_holds_receiver(channel, channel_type: str, receiver: str) -> bool:
    """Whether *channel* already knows how to reach *receiver*.

    Used to disambiguate when several running instances of one type exist and
    the task carries no instance_id: the right one is the login that actually
    holds this receiver's context token. Only weixin keeps such per-receiver
    tokens; for other types we can't tell, so we don't claim a match.
    """
    if channel_type == "weixin":
        tokens = getattr(channel, "_context_tokens", None)
        return bool(tokens and receiver in tokens)
    return False


def _recover_instance_id_from_directory(channel_type: str, receiver: str) -> str:
    """The instance that first saw *receiver*, per the recipient directory.

    A receiver id is only meaningful within the instance that issued it — a
    Feishu ``open_id`` is scoped to one app, so sending it through a different
    Feishu instance fails with ``open_id cross app``. When a task carries no
    (or a stale) instance_id, the recipient directory — keyed by
    ``(instance_id, receiver)`` — is the authoritative place to recover the
    right instance. Returns "" when unknown.
    """
    receiver = str(receiver or "").strip()
    channel_type = str(channel_type or "").strip()
    if not receiver:
        return ""
    try:
        store = _get_shared_recipient_store()
        for entry in store.list():
            if (
                entry.get("channel_type") == channel_type
                and entry.get("receiver") == receiver
            ):
                iid = str(entry.get("instance_id") or "").strip()
                if iid:
                    return iid
    except Exception as e:
        logger.debug(f"[Scheduler] recipient directory lookup failed: {e}")
    return ""


def _resolve_delivery_channel(channel_type: str, instance_id: str = "", receiver: str = ""):
    """The channel object a scheduled task should send through.

    Prefers the *live running instance* held by ChannelManager, looked up by
    instance_id. That matters because a running channel carries state a freshly
    built one does not: in-memory login/context tokens, an open websocket, the
    per-instance credentials it started with. Building a bare
    ``create_channel(channel_type)`` instead would grab whichever instance the
    singleton cache happens to hold — a never-started empty object once the real
    bot runs as a channel_instance, which is exactly the delivery bug this avoids.

    Resolution order:
      1. Exact match by instance_id (or legacy instance_id == channel_type).
      2. Task carries no (or a stale) instance_id — recover the right live
         instance without ever sending to the wrong login:
           a. Ask the recipient directory which instance first saw this
              receiver, then use that instance. This is what keeps an
              app-scoped id (a Feishu open_id) from being sent through a
              different app instance (``open_id cross app``).
           b. Else pick the instance already holding the receiver's token
              (weixin keeps per-receiver tokens).
           c. Else, only when exactly one instance of the type runs, use it.
              With several running instances and no way to tell them apart we
              refuse to guess (returning that lone-or-none live instance),
              since a wrong pick delivers to the wrong account.
      3. Fall back to ``create_channel`` (legacy single-instance) only when no
         manager or no running instance of the type exists.
    """
    instance_id = str(instance_id or "").strip()
    receiver = str(receiver or "").strip()
    try:
        from common.channel_registry import get_channel_manager
        manager = get_channel_manager()
        if manager is not None:
            # (1) Exact key: instance_id, or channel_type for legacy singletons.
            lookup = instance_id or channel_type
            live = manager.get_channel(lookup)
            if live is not None:
                return live

            candidates = manager.find_channels_by_type(channel_type)
            if candidates:
                # (2a) Authoritative: the directory knows which instance owns
                # this receiver. Resolve to that exact instance.
                recovered = _recover_instance_id_from_directory(channel_type, receiver)
                if recovered:
                    live = manager.get_channel(recovered)
                    if live is not None:
                        logger.info(
                            f"[Scheduler] Recovered instance '{recovered}' for "
                            f"{channel_type} receiver={receiver} from recipient directory"
                        )
                        return live

                # (2b) Token-holder (weixin): the login that already knows them.
                if receiver:
                    for _name, ch in candidates:
                        if _channel_holds_receiver(ch, channel_type, receiver):
                            return ch

                # (2c) Only safe to auto-pick when the type runs a single
                # instance. Several instances with app-scoped receiver ids
                # (Feishu open_id) must not be guessed — that would deliver to
                # the wrong app. Leave it to the bare fallback / hard failure.
                if len(candidates) == 1:
                    return candidates[0][1]
                logger.warning(
                    f"[Scheduler] {channel_type} has {len(candidates)} running "
                    f"instances but the task named none and receiver={receiver} "
                    f"is not in the recipient directory; cannot pick safely"
                )
    except Exception as e:
        logger.debug(f"[Scheduler] No live channel for instance '{instance_id}': {e}")

    from channel.channel_factory import create_channel
    return create_channel(channel_type)


def _is_channel_ready(
    channel_type: str, receiver: str, agent_id: str = None, instance_id: str = ""
) -> bool:
    """Best-effort readiness probe for outbound channels.

    Returns False when we know the send will drop (e.g. weixin not yet
    logged in, web session has no polling queue), so the scheduler can
    defer instead of consuming the task. Unknown channels return True
    to preserve previous behaviour.

    Probes the same live instance delivery will use, so a "ready" answer means
    *that* instance is ready, not some other login of the same channel type.
    """
    if not channel_type or channel_type == "unknown":
        return True
    try:
        channel = _resolve_delivery_channel(channel_type, instance_id, receiver)
        if channel is None:
            return False

        if channel_type == "weixin":
            tokens = getattr(channel, "_context_tokens", None)
            if not tokens or receiver not in tokens:
                # The token check only means something for the *running* login.
                # If we're staring at a bare, never-started singleton (no live
                # instance in the manager), its token map is empty no matter
                # what — blocking here would defer forever (issue #3120). Fall
                # back to the pre-check behaviour and let the send attempt run.
                if not _is_live_channel_instance(channel):
                    logger.debug(
                        "[Scheduler] weixin readiness inconclusive (no live "
                        f"instance for receiver={receiver}); allowing send attempt"
                    )
                    return True
                return False
            return True

        if channel_type == "web":
            # A web session is always a valid delivery target: the message is
            # persisted to the conversation history regardless, and an idle
            # client keeps polling /poll so it will surface the push on its next
            # tick. Gating on the in-memory session_queues (which only exists
            # after the user has sent a message this process life) used to make
            # a scheduled push silently defer forever after a restart, even
            # though the session and the polling client were both still there.
            return True

        return True
    except Exception as e:
        logger.warning(f"[Scheduler] Channel readiness check failed for {channel_type}: {e}")
        return True


def get_task_store(workspace_root: str = None, agent_id: str = None):
    """The one global task store. ``workspace_root``/``agent_id`` are ignored
    (kept for call-site compatibility); tasks are filtered by ``agent_id`` at
    the query, not by which store they live in."""
    if _task_store is not None:
        return _task_store
    # Lazily build the store even if the service hasn't started yet, so tools /
    # handlers that only read or write tasks work before scheduler warmup.
    with _init_lock:
        if _task_store is not None:
            return _task_store
        try:
            from agent.tools.scheduler.task_store import TaskStore
            from common.state_dir import scheduler_file_global

            globals()["_task_store"] = TaskStore(str(scheduler_file_global()))
            _migrate_legacy_task_stores(globals()["_task_store"])
        except Exception as e:
            logger.error(f"[Scheduler] Failed to open global task store: {e}")
            return None
    return _task_store


def get_scheduler_service(workspace_root: str = None, agent_id: str = None):
    """The one global scheduler service (``workspace_root``/``agent_id`` ignored)."""
    return _scheduler_service


def get_recipient_store(workspace_root: str = None, agent_id: str = None):
    """Get the shared trusted recipient directory.

    Shared across Agents, so the ``workspace_root``/``agent_id`` arguments are
    ignored; they are kept only so existing call sites need no change.
    """
    return _get_shared_recipient_store()


def reset_scheduler_services(stop: bool = True) -> None:
    """Stop and forget the global scheduler service, primarily for reloads/tests."""
    global _scheduler_service, _task_store, _recipient_store, _legacy_stores_migrated
    with _init_lock:
        if stop and _scheduler_service is not None:
            try:
                _scheduler_service.stop()
            except Exception:
                pass
        _recipient_store = None
        _scheduler_service = None
        _task_store = None
        _legacy_stores_migrated = False


def stop_scheduler(agent_id: str = None, workspace_root: str = None) -> bool:
    """No-op under the global scheduler.

    Tasks are no longer sharded per Agent, so removing one Agent from the roster
    does not stop any scheduler — the single global service keeps running the
    remaining Agents' tasks. A removed/disabled Agent's tasks simply stop
    matching at execution time (they fall back to the default owner or are
    skipped). Kept for call-site compatibility; always returns False."""
    return False


def _remember_delivered_output(
    agent_bridge,
    task: dict,
    channel_type: str,
    content: str,
    agent_id: str = None,
) -> None:
    """Best-effort persistence of the message the scheduler sent to a user.

    Uses notify_session_id (the real chat session_id stored at task creation time)
    so that group chats correctly associate the output with the user's conversation.
    Falls back to receiver for backward compatibility with old tasks.

    Per-action-type behaviour:
        - agent_task / tool_call / skill_call: gated by ``scheduler_inject_to_session``
          (default True). These produce AI-generated content worth remembering.
        - send_message: additionally gated by ``scheduler_inject_send_message``
          (default False) on push-capable IM channels. Fixed reminder text rarely
          benefits follow-up Q&A there and would just consume context tokens.

    The web channel is the exception: it cannot push to an idle client, so the
    conversation history is the *only* place a delivered message shows up when
    the user isn't actively chatting (e.g. right after a restart). We therefore
    always persist for web, including send_message, so nothing is silently lost.
    """
    if not content:
        return
    action = task.get("action", {})
    action_type = action.get("type", "")

    # send_message defaults to NOT being injected on IM channels; explicit
    # opt-in via config. Web always persists (see docstring) since history is
    # its only delivery surface for an idle client.
    if action_type == "send_message" and channel_type != "web":
        if not conf().get("scheduler_inject_send_message", False):
            return

    session_id = action.get("notify_session_id") or action.get("receiver")
    if not session_id:
        return
    try:
        remember = getattr(agent_bridge, "remember_scheduled_output", None)
        if remember:
            task_desc = action.get("task_description") or action.get("content", "")
            kwargs = {
                "channel_type": channel_type,
                "task_description": task_desc,
            }
            if hasattr(agent_bridge, "agent_registry"):
                kwargs["agent_id"] = agent_id
            remember(session_id, str(content), **kwargs)
    except Exception as e:
        logger.warning(
            f"[Scheduler] Failed to remember delivered output for {session_id}: {e}"
        )


# Longest delivered-content snippet stored on a scheduler run for at-a-glance
# history ("what did this task actually send?"). The complete text also lives in
# the receiver's session and is recovered on demand via get_run_detail, but that
# session copy is pruned aggressively (only the last few scheduler pairs survive)
# — so this preview is the durable, always-available record and is kept roomy
# enough to stand alone in the detail view. When the body exceeds this we append
# an ellipsis so a truncated preview never looks like the whole message.
_OUTPUT_PREVIEW_LIMIT = 1000


def _record_scheduler_run(task: dict, agent_id: str, trigger: str = "scheduled"):
    """Open a ``runs`` row for one scheduler execution, or ``None`` if runs
    tracking is unavailable.

    Reuses the same global ``runs`` table that native turns, delegations and
    subagents write to (now agent-scoped in the one global ``index.db``), so a
    scheduled job is just another addressable unit of work: ``task_source`` is
    ``"scheduler"`` and ``task_id`` is the task's id. Returns ``(store, run_id)``
    to be closed by :func:`finish_run`, or ``None`` when the store/runs table
    isn't ready — recording a run must never block a delivery.

    ``trigger`` records how the tick fired — ``"scheduled"`` for the timer,
    ``"manual"`` for a user-initiated "run now" — so history can tell an
    automatic run apart from one a person kicked off.
    """
    try:
        import uuid

        from agent.memory import get_conversation_store

        action = task.get("action", {})
        session_id = action.get("notify_session_id") or action.get("receiver") or ""
        run_id = uuid.uuid4().hex
        store = get_conversation_store()  # routing-aware: scoped to agent_id
        created = store.create_run(
            run_id,
            agent_id=agent_id or "",
            session_id=session_id,
            task_id=str(task.get("id") or ""),
            task_source="scheduler",
            extras={
                "action_type": action.get("type", ""),
                "channel_type": _primary_channel_type(action.get("channel_type")),
                # The exact delivery instance, so the detail view can show which
                # channel instance ran it (resolved to a friendly name client-side).
                "instance_id": action.get("instance_id") or "",
                "task_name": task.get("name", ""),
                "trigger": trigger,
            },
        )
        if not created:
            return None
        return store, run_id
    except Exception as e:
        logger.debug(f"[Scheduler] run recording unavailable: {e}")
        return None


def _run_scheduled_task(
    task: dict, agent_bridge, agent_id: str, trigger: str = "scheduled"
) -> bool:
    """Dispatch one task, recording an execution ``run`` around the attempt.

    Readiness is checked first: a not-ready channel is a *deferral*, not an
    execution, so no run row is opened for it (that would log a failed run every
    tick until the channel wakes). Once we commit to running, a run is opened,
    the action dispatched, and the run closed ``done``/``error`` from the
    outcome. Run recording is best-effort and never changes the delivery result.

    A mutable ``sink`` collects the delivered content each ``_execute_*`` sends,
    so the closing ``finish_run`` can store a short ``output_preview`` on the
    run — a peek at "what did this send?" without opening the session.
    """
    action = task.get("action", {})
    action_type = action.get("type")
    channel_type = _primary_channel_type(action.get("channel_type"))
    receiver = action.get("receiver", "")
    instance_id = action.get("instance_id") or ""

    if not _is_channel_ready(channel_type, receiver, agent_id, instance_id):
        logger.warning(
            f"[Scheduler] Task {task.get('id')}: channel "
            f"'{channel_type}' not ready for receiver={receiver} "
            f"(no inbound msg cached since restart?); deferring"
        )
        return False

    run = _record_scheduler_run(task, agent_id, trigger=trigger)
    sink: Dict[str, str] = {}
    status = "done"
    error = ""
    try:
        if action_type == "agent_task":
            ok = _execute_agent_task(task, agent_bridge, agent_id, output_sink=sink)
        elif action_type == "send_message":
            ok = _execute_send_message(task, agent_bridge, agent_id, output_sink=sink)
        elif action_type == "tool_call":
            ok = _execute_tool_call(task, agent_bridge, agent_id, output_sink=sink)
        elif action_type == "skill_call":
            ok = _execute_skill_call(task, agent_bridge, agent_id, output_sink=sink)
        else:
            logger.warning(f"[Scheduler] Unknown action type: {action_type}")
            ok = True
        if not ok:
            status = "error"
            error = "deferred or delivery failed"
        return ok
    except Exception as e:
        status = "error"
        error = str(e)
        raise
    finally:
        if run is not None:
            store, run_id = run
            extras = None
            preview = (sink.get("preview") or "").strip()
            if preview:
                # Append an ellipsis on truncation so a clipped preview never
                # reads as the complete message (the full body is recoverable
                # via get_run_detail's join back to the session).
                if len(preview) > _OUTPUT_PREVIEW_LIMIT:
                    preview = preview[:_OUTPUT_PREVIEW_LIMIT].rstrip() + "…"
                extras = {"output_preview": preview}
            try:
                store.finish_run(run_id, status=status, error=error, extras=extras)
            except Exception as e:
                logger.debug(f"[Scheduler] finish_run failed for {run_id}: {e}")


def _execute_agent_task(
    task: dict, agent_bridge, agent_id: str = None, output_sink: dict = None
) -> bool:
    """
    Execute an agent_task action - let Agent handle the task.
    Returns True on successful delivery, False to retry next tick.
    """
    try:
        action = task.get("action", {})
        task_description = action.get("task_description")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = _primary_channel_type(action.get("channel_type"))

        if not task_description:
            logger.error(f"[Scheduler] Task {task['id']}: No task_description specified")
            return True  # malformed task, don't loop forever

        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        # Check for unsupported channels
        if channel_type == "dingtalk":
            logger.warning(f"[Scheduler] Task {task['id']}: DingTalk channel does not support scheduled messages (Stream mode limitation). Task will execute but message cannot be sent.")

        logger.info(f"[Scheduler] Task {task['id']}: Executing agent task '{task_description}'")

        # Wrap the raw description with an execution directive. The stored
        # description is often phrased as a rule ("every day at 08:00 send...").
        # Without this prefix the agent may treat it as a spec to acknowledge
        # instead of a task to run right now, especially after a mid-run failure.
        execution_prompt = (
            "这是一个定时任务的立即执行请求，当前已到执行时刻。"
            "请直接完成下面描述的任务并产出最终交付内容，"
            "无需复述、确认或讨论任务规则，不要输出任务指令或调试信息。"
            "若执行失败，返回简洁明确的失败说明。\n\n"
            f"任务描述：\n{task_description}"
        )

        # Create a unique session_id for this scheduled task to avoid polluting user's conversation
        # Format: scheduler_<receiver>_<task_id> to ensure isolation
        scheduler_session_id = f"scheduler_{receiver}_{task['id']}"

        # Create context for Agent
        context = Context(ContextType.TEXT, execution_prompt)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id

        # Channel-specific setup
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "dingtalk":
            # DingTalk requires msg object, set to None for scheduled tasks
            context["msg"] = None
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
        elif channel_type == "wecom_bot":
            context["msg"] = None

        # Use Agent to execute the task
        # Mark this as a scheduled task execution to prevent recursive task creation
        context["is_scheduled_task"] = True

        try:
            # Don't clear history - scheduler tasks use isolated session_id so they won't pollute user conversations
            reply = agent_bridge.agent_reply(execution_prompt, context=context, on_event=None, clear_history=False)

            if not (reply and reply.content):
                # Empty is a valid outcome: the task ran and decided there was
                # nothing worth reporting (conditional reminders, monitors with
                # no alert). Send nothing rather than a placeholder message.
                logger.info(
                    f"[Scheduler] Task {task['id']}: agent produced no content, nothing to send"
                )
                return True

            if action.get("silent", False):
                logger.info(
                    f"[Scheduler] Task {task['id']} executed successfully in silent mode"
                )
                return True

            channel = _resolve_delivery_channel(channel_type, action.get("instance_id") or "", receiver)
            if not channel:
                logger.error(f"[Scheduler] Failed to resolve channel: {channel_type}")
                return False

            if channel_type == "web" and hasattr(channel, 'request_to_session'):
                request_id = context.get("request_id")
                if request_id:
                    channel.request_to_session[request_id] = receiver

            try:
                channel.send(reply, context)
            except Exception as e:
                logger.error(f"[Scheduler] Failed to send result: {e}")
                return False

            if output_sink is not None:
                output_sink["preview"] = str(reply.content)
            _remember_delivered_output(
                agent_bridge, task, channel_type, reply.content, agent_id
            )
            logger.info(f"[Scheduler] Task {task['id']} executed successfully, result sent to {receiver}")
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute task via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            return False

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_agent_task: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def _execute_send_message(
    task: dict, agent_bridge, agent_id: str = None, output_sink: dict = None
) -> bool:
    """Execute a send_message action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        content = action.get("content", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = _primary_channel_type(action.get("channel_type"))

        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        # Create context for sending message
        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id

        # Channel-specific context setup
        if channel_type == "web":
            # Web channel needs request_id
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
            logger.debug(f"[Scheduler] Generated request_id for web channel: {request_id}")
        elif channel_type == "feishu":
            # Feishu channel: for scheduled tasks, send as new message (no msg_id to reply to)
            # Use chat_id for groups, open_id for private chats
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            # Keep isgroup as is, but set msg to None (no original message to reply to)
            # Feishu channel will detect this and send as new message instead of reply
            context["msg"] = None
            logger.debug(f"[Scheduler] Feishu: receive_id_type={context['receive_id_type']}, is_group={is_group}, receiver={receiver}")
        elif channel_type == "dingtalk":
            # DingTalk channel setup
            context["msg"] = None
            # 如果是单聊，需要传递 sender_staff_id
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
                    logger.debug(f"[Scheduler] DingTalk single chat: sender_staff_id={sender_staff_id}")
                else:
                    logger.warning(f"[Scheduler] Task {task['id']}: DingTalk single chat message missing sender_staff_id")
        elif channel_type == "wecom_bot":
            context["msg"] = None
        elif channel_type == "qq":
            context["msg"] = None

        # Create reply
        reply = Reply(ReplyType.TEXT, content)

        # Get the live instance for this task and send through it.
        channel = _resolve_delivery_channel(channel_type, action.get("instance_id") or "", receiver)
        if not channel:
            logger.error(f"[Scheduler] Failed to resolve channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            channel.send(reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send message: {e}")
            return False

        if output_sink is not None:
            output_sink["preview"] = str(content)
        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: sent message to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_send_message: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def _execute_tool_call(
    task: dict, agent_bridge, agent_id: str = None, output_sink: dict = None
) -> bool:
    """Execute a tool_call action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        tool_name = action.get("call_name") or action.get("tool_name")
        tool_params = action.get("call_params") or action.get("tool_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = _primary_channel_type(action.get("channel_type"))

        if not tool_name:
            logger.error(f"[Scheduler] Task {task['id']}: No tool_name specified")
            return True
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        from agent.tools.tool_manager import ToolManager
        tool = ToolManager().create_tool(tool_name)
        if not tool:
            logger.error(f"[Scheduler] Task {task['id']}: Tool '{tool_name}' not found")
            return True

        logger.info(f"[Scheduler] Task {task['id']}: Executing tool '{tool_name}' with params {tool_params}")
        result = tool.execute(tool_params)
        content = result.result if hasattr(result, 'result') else str(result)
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id

        request_id = None
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        reply = Reply(ReplyType.TEXT, content)

        channel = _resolve_delivery_channel(channel_type, action.get("instance_id") or "", receiver)
        if not channel:
            logger.error(f"[Scheduler] Failed to resolve channel: {channel_type}")
            return False

        if channel_type == "web" and request_id and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            channel.send(reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send tool result: {e}")
            return False

        if output_sink is not None:
            output_sink["preview"] = str(content)
        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: sent tool result to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_tool_call: {e}")
        return False


def _execute_skill_call(
    task: dict, agent_bridge, agent_id: str = None, output_sink: dict = None
) -> bool:
    """Execute a skill_call action by asking Agent to run the skill.
    Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        skill_name = action.get("call_name") or action.get("skill_name")
        skill_params = action.get("call_params") or action.get("skill_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("isgroup", False)
        channel_type = _primary_channel_type(action.get("channel_type"))

        if not skill_name:
            logger.error(f"[Scheduler] Task {task['id']}: No skill_name specified")
            return True
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        logger.info(f"[Scheduler] Task {task['id']}: Executing skill '{skill_name}' with params {skill_params}")

        scheduler_session_id = f"scheduler_{receiver}_{task['id']}"
        param_str = ", ".join([f"{k}={v}" for k, v in skill_params.items()])
        query = f"Use {skill_name} skill"
        if param_str:
            query += f" with {param_str}"

        context = Context(ContextType.TEXT, query)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id

        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        try:
            reply = agent_bridge.agent_reply(query, context=context, on_event=None, clear_history=False)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute skill via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            return False

        if not (reply and reply.content):
            logger.error(f"[Scheduler] Task {task['id']}: No result from skill execution")
            return True

        content = reply.content
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        channel = _resolve_delivery_channel(channel_type, action.get("instance_id") or "", receiver)
        if not channel:
            logger.error(f"[Scheduler] Failed to resolve channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            req_id = context.get("request_id")
            if req_id:
                channel.request_to_session[req_id] = receiver

        try:
            channel.send(Reply(ReplyType.TEXT, content), context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send skill result: {e}")
            return False

        if output_sink is not None:
            output_sink["preview"] = str(content)
        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: skill result sent to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_skill_call: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def attach_scheduler_to_tool(tool, context: Context = None):
    """
    Attach scheduler components to a SchedulerTool instance

    Args:
        tool: SchedulerTool instance
        context: Current context (optional)
    """
    if context:
        agent_id = context.get("agent_id")
        task_store = get_task_store(agent_id=agent_id)
        scheduler_service = get_scheduler_service(agent_id=agent_id)
        recipient_store = get_recipient_store(agent_id=agent_id)
        if task_store:
            tool.task_store = task_store
        if scheduler_service:
            tool.scheduler_service = scheduler_service
        if recipient_store:
            tool.recipient_store = recipient_store
        tool.current_context = context

        channel_type = context.get("channel_type") or conf().get("channel_type", "unknown")
        if not tool.config:
            tool.config = {}
        tool.config["channel_type"] = channel_type

        # Only accepted inbound contexts become cross-channel targets.  Do not
        # persist ephemeral credentials; the channel keeps enforcing its own
        # authentication and readiness rules at delivery time.
        if recipient_store and channel_type != "web":
            # instance_id is what a scheduled delivery must route back through:
            # two instances of one channel type have separate logins and receiver
            # id spaces. It rides on the inbound context; when absent (legacy
            # single-instance channel) the store falls back to the channel type.
            recipient_store.remember(
                channel_type,
                context.get("receiver"),
                name=tool._get_receiver_name(context),
                is_group=context.get("isgroup", False),
                session_id=context.get("session_id"),
                instance_id=context.get("instance_id") or "",
            )
