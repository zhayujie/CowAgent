"""Running a sub agent: one task, its own context, a summary back.

The parent's context only ever sees the spawn call and the returned summary.
Everything the sub agent read, ran and discarded on the way stays out, which is
the point of spawning one at all.
"""

from __future__ import annotations

import contextvars
import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from common.log import logger
from common.runtime_identity import identity_scope

# Nesting depth of the currently running work. 0 is the main Agent. Lives in a
# ContextVar rather than on the Agent because sub agents run on worker threads,
# and contextvars.copy_context() carries it across the handoff.
_depth: contextvars.ContextVar[int] = contextvars.ContextVar("cow_subagent_depth", default=0)


def current_depth() -> int:
    return _depth.get()


@dataclass(frozen=True)
class SubagentSettings:
    enabled: bool = True
    max_depth: int = 1
    max_concurrent: int = 3
    timeout_seconds: float = 300.0

    @classmethod
    def from_config(cls) -> "SubagentSettings":
        from config import conf

        raw = conf().get("subagent") or {}
        if not isinstance(raw, dict):
            logger.warning("[SubAgent] 'subagent' config must be an object; ignoring")
            raw = {}

        def _bounded(key, default, low, high, cast):
            try:
                value = cast(raw.get(key, default))
            except (TypeError, ValueError):
                logger.warning(f"[SubAgent] Invalid {key!r}; using {default}")
                return default
            if not low <= value <= high:
                logger.warning(
                    f"[SubAgent] {key}={value} out of range [{low}, {high}]; using {default}"
                )
                return default
            return value

        return cls(
            # On unless switched off: an install that has never heard of this
            # setting gets sub agents, which is the behaviour worth defaulting
            # to. Turning it off is the deliberate act.
            enabled=bool(raw.get("enabled", True)),
            max_depth=_bounded("max_depth", 1, 1, 5, int),
            max_concurrent=_bounded("max_concurrent", 3, 1, 10, int),
            timeout_seconds=_bounded("timeout_seconds", 300.0, 10.0, 3600.0, float),
        )


@dataclass
class SubagentTask:
    goal: str
    context: str = ""
    subagent_type: Optional[str] = None


def _build_brief(task: SubagentTask, template) -> str:
    parts = [template.prompt, "", "YOUR TASK:", task.goal.strip()]
    if task.context.strip():
        parts += ["", "CONTEXT:", task.context.strip()]
    return "\n".join(parts)


def _private_tools(parent, template) -> list:
    """This template's tools, as instances no other run shares.

    The agent loop drives tools by assignment — it sets `context`,
    `cancel_event` and `progress_callback` on the instance before each call and
    clears them after. Two sub agents running at once on one instance would
    therefore clear each other's cancel_event mid-call, quietly disarming the
    timeout, and cross-report each other's progress. A shallow copy gives each
    run its own slots for those attributes while leaving anything the tool holds
    open (a browser session, an MCP client) shared, as it already is today.
    """
    return [copy.copy(tool) for tool in template.select_tools(list(parent.tools))]


def _build_child(parent, template, task: SubagentTask):
    """A sibling of the parent Agent that shares its model and workspace.

    Not a copy: no memory manager, no persona files, no message history. It
    knows the task and nothing else, so anything it needs has to arrive through
    the goal and context the parent wrote.
    """
    from agent.protocol.agent import Agent

    child = Agent(
        system_prompt=template.prompt,
        description=f"sub agent ({template.name})",
        model=parent.model,
        tools=_private_tools(parent, template),
        output_mode="logger",
        # Half the parent's budget. A sub agent's task is one self-contained
        # piece of work by definition, and it starts with an empty context, so
        # it should not be able to run as long as the whole conversation that
        # delegated it. Overrunning is not fatal: the loop asks for a summary
        # of what it managed and that is what comes back.
        max_steps=max(1, parent.max_steps // 2),
        max_context_tokens=parent.max_context_tokens,
        memory_manager=None,
        name=f"subagent:{template.name}",
        workspace_dir=parent.workspace_dir,
        skill_manager=parent.skill_manager if template.inherits_skills() else None,
        enable_skills=parent.enable_skills and template.inherits_skills(),
        runtime_info=parent.runtime_info,
        skip_context_files=True,
    )
    child.extra_system_suffix = _build_brief(task, template)
    # Same working directory and same permission mode as the parent: the tool
    # copies already point at the parent's cwd, and delegating to a sub agent
    # must not become a way around the session's permissions.
    child.project_dir = parent.project_dir
    child.permission_mode = parent.permission_mode
    return child


def _notify(on_state, index: int, state: Dict[str, Any]) -> None:
    """Report a task's state to the caller. Never lets a reporting problem
    reach the run it is only meant to describe."""
    if not on_state:
        return
    try:
        on_state(index, state)
    except Exception as e:
        logger.debug(f"[SubAgent] state callback failed: {e}")


def _open_run(parent, run_id: str, template) -> Optional[Any]:
    """Record the start of a spawned run, returning the store to close it with.

    None means the spawn is not being recorded, either because the parent's
    workspace is unknown — there is no database to attribute it to, and
    guessing a global one would write another workspace's history — or because
    the write failed. Bookkeeping never blocks a spawn.

    The parent's run id is read before the caller enters its own identity
    scope, so it is still the ambient one and becomes this run's parent.
    """
    workspace = getattr(parent, "workspace_dir", None)
    if not workspace:
        return None
    try:
        from agent.memory import get_conversation_store
        from common.utils import current_agent_run_id

        store = get_conversation_store(workspace)
        store.create_run(
            run_id,
            agent_id=getattr(parent, "_current_agent_id", "") or "",
            session_id=getattr(parent, "_current_session_id", "") or "",
            parent_run_id=current_agent_run_id() or "",
            extras={"subagent_type": template.name},
        )
        return store
    except Exception as e:
        logger.debug(f"[SubAgent] could not record run {run_id}: {e}")
        return None


# What the runs table calls a finished run, keyed by the status this module
# reports to its caller.
_RUN_STATUS = {"completed": "done", "cancelled": "cancelled", "failed": "failed"}


def _close_run(store, run_id: str, result: Dict[str, Any]) -> None:
    """Mark a spawned run finished. Silent on failure, like _open_run."""
    if store is None:
        return
    try:
        store.finish_run(
            run_id,
            status=_RUN_STATUS.get(result.get("status", ""), "done"),
            error=str(result.get("error", "")),
        )
    except Exception as e:
        logger.debug(f"[SubAgent] could not close run {run_id}: {e}")


def _run_one(parent, template, task: SubagentTask, index: int, cancel_event,
             on_state=None, on_event=None) -> Dict[str, Any]:
    started = time.time()
    run_id = uuid.uuid4().hex[:12]
    # Before identity_scope below, so the parent's run id is still ambient.
    run_store = _open_run(parent, run_id, template)
    result: Dict[str, Any] = {"task_index": index, "subagent_type": template.name}
    _notify(on_state, index, {"status": "running", "subagent_type": template.name})

    child_events = None
    if on_event:
        def child_events(event: Dict[str, Any]) -> None:
            # Same contract as _notify: watching a run must not be able to
            # break it.
            try:
                on_event(index, event)
            except Exception as e:
                logger.debug(f"[SubAgent] event callback failed: {e}")

    try:
        # A fresh run_id under the parent's agent and session: state written by
        # the sub agent lands in the right workspace, and its trace is
        # attributable to this spawn rather than to the parent's turn.
        with identity_scope(run_id=run_id):
            _depth.set(_depth.get() + 1)
            child = _build_child(parent, template, task)
            summary = child.run_stream(
                task.goal, clear_history=True, cancel_event=cancel_event,
                on_event=child_events,
            )
        result["status"] = "cancelled" if cancel_event.is_set() else "completed"
        result["summary"] = summary or ""
    except Exception as e:
        logger.warning(f"[SubAgent] task {index} ({template.name}) failed: {e}")
        result["status"] = "failed"
        result["error"] = str(e)

    result["duration_seconds"] = round(time.time() - started, 2)
    _close_run(run_store, run_id, result)
    _notify(on_state, index, result)
    return result


def run_tasks(
    parent,
    tasks: List[SubagentTask],
    templates,
    settings: SubagentSettings,
    on_state=None,
    on_event=None,
) -> List[Dict[str, Any]]:
    """Run every task and return one result per task, in the order given.

    Tasks run concurrently. A task that times out is cancelled and reported as
    such rather than abandoned, so the parent always gets a full-length result
    list and can tell the difference between "nothing found" and "never ran".

    `on_state(index, state)` is called as each task starts and again as it
    settles, so a caller can follow tasks individually while they run rather
    than learning about all of them at the end. Every task that reports a start
    reports an end, timeouts included.

    `on_event(index, event)` receives the sub agent's own stream events as they
    happen. What the parent's context sees is still only the returned summary;
    this is for whoever is watching the run, who otherwise spends the minutes
    it takes looking at a spinner.
    """
    cancel_events = [threading.Event() for _ in tasks]
    resolved = []
    for task in tasks:
        name = task.subagent_type or ""
        resolved.append(templates[name] if name in templates else templates[_default_name(templates)])

    pool = ThreadPoolExecutor(
        max_workers=min(len(tasks), settings.max_concurrent),
        thread_name_prefix="subagent",
    )
    try:
        futures = []
        for index, (task, template) in enumerate(zip(tasks, resolved)):
            # copy_context carries both the runtime identity and the depth
            # counter into the worker thread; without it the sub agent would
            # run at depth 0 under the default Agent.
            ctx = contextvars.copy_context()
            futures.append(
                pool.submit(
                    ctx.run, _run_one, parent, template, task, index,
                    cancel_events[index], on_state, on_event,
                )
            )

        deadline = time.time() + settings.timeout_seconds
        results: List[Optional[Dict[str, Any]]] = [None] * len(tasks)
        for index, future in enumerate(futures):
            remaining = max(0.0, deadline - time.time())
            try:
                results[index] = future.result(timeout=remaining)
            except FutureTimeout:
                # Tell the run to stop and report it. The worker winds down at
                # its next checkpoint, which may be a whole LLM response away.
                cancel_events[index].set()
                results[index] = {
                    "task_index": index,
                    "subagent_type": resolved[index].name,
                    "status": "timeout",
                    "error": (
                        f"Exceeded the {settings.timeout_seconds:g}s sub agent budget. "
                        f"Split the task or raise subagent.timeout_seconds."
                    ),
                }
                # The worker is still winding down and will not report this
                # itself, so close the task out here rather than leave whoever
                # is following it waiting on a task that is never coming back.
                _notify(on_state, index, results[index])
    finally:
        # Deliberately not waiting: a `with` block would join the very threads
        # we just gave up on, so the tool call would overrun the budget it is
        # meant to enforce. Cancelled runs stop on their own and touch nothing
        # the parent shares.
        pool.shutdown(wait=False)

    return [r for r in results if r is not None]


def _default_name(templates) -> str:
    from agent.subagent.templates import DEFAULT_TEMPLATE_NAME

    if DEFAULT_TEMPLATE_NAME in templates:
        return DEFAULT_TEMPLATE_NAME
    return next(iter(templates))
