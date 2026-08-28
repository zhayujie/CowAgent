"""Guarded delegation between independently configured agent workspaces."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from agent.tools.base_tool import BaseTool, ToolResult
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from common.log import logger

# Marks delegated runs so they can be told apart from turns a user started.
TASK_SOURCE = "delegation"

# Terminal states a delegated run can settle into.
_TERMINAL = ("done", "failed", "cancelled")

# How many finished delegations stay queryable in memory. The durable answer
# lives in the runs table; this is only a fast path for the current process.
_MAX_TRACKED = 200


@dataclass(frozen=True)
class DelegationPolicy:
    enabled: bool = True
    allowed_targets: Optional[Mapping[str, Tuple[str, ...]]] = None
    max_depth: int = 3
    timeout_seconds: float = 120.0
    max_message_chars: int = 8000
    default_wait_seconds: float = 30.0

    @classmethod
    def from_config(cls, raw) -> "DelegationPolicy":
        if raw is False:
            return cls(enabled=False)
        if raw is None or raw is True:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ValueError("agent_delegation must be an object or boolean")

        allow = raw.get("allowed_targets")
        normalized = None
        if allow is not None:
            if not isinstance(allow, Mapping):
                raise ValueError("allowed_targets must map source Agent IDs to lists")
            normalized = {}
            for source, targets in allow.items():
                if not isinstance(source, str) or not isinstance(targets, (list, tuple)):
                    raise ValueError("allowed_targets entries must contain lists")
                if not all(isinstance(target, str) for target in targets):
                    raise ValueError("allowed target IDs must be strings")
                normalized[source] = tuple(targets)

        max_depth = int(raw.get("max_depth", 3))
        timeout_seconds = float(raw.get("timeout_seconds", 120))
        max_message_chars = int(raw.get("max_message_chars", 8000))
        default_wait_seconds = float(raw.get("default_wait_seconds", 30))
        if not 1 <= max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")
        if not 0.01 <= timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be between 0.01 and 600")
        if not 1 <= max_message_chars <= 100000:
            raise ValueError("max_message_chars must be between 1 and 100000")
        if default_wait_seconds < 0:
            raise ValueError("default_wait_seconds must not be negative")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            allowed_targets=normalized,
            max_depth=max_depth,
            timeout_seconds=timeout_seconds,
            max_message_chars=max_message_chars,
            default_wait_seconds=default_wait_seconds,
        )

    def allows(self, source_agent_id: str, target_agent_id: str) -> bool:
        if not self.enabled:
            return False
        if self.allowed_targets is None:
            return source_agent_id != target_agent_id
        targets = self.allowed_targets.get(source_agent_id, ())
        return "*" in targets or target_agent_id in targets


_relay_locks = {}
_relay_locks_guard = threading.Lock()


def _relay_lock(session_id: str) -> threading.Lock:
    with _relay_locks_guard:
        return _relay_locks.setdefault(session_id, threading.Lock())


@dataclass
class _Delegation:
    """In-process view of one delegated run, keyed by its run id."""

    run_id: str
    source_agent_id: str
    target_agent_id: str
    target_agent_name: str
    session_id: str
    request_id: str
    depth: int
    timeout_seconds: float
    status: str = "running"
    content: Any = None
    error: str = ""
    # Set when the cancellation came from the time budget rather than a
    # caller, so the outcome can say "timed out" no matter who noticed first.
    deadline_exceeded: bool = False
    done: threading.Event = field(default_factory=threading.Event)

    def settle(self, status: str, content: Any = None, error: str = "") -> bool:
        """Record the outcome. The first terminal state wins, so a target that
        keeps working past its deadline cannot overwrite the cancellation.
        """
        if self.status in _TERMINAL:
            return False
        self.status = status
        self.content = content
        self.error = error
        self.done.set()
        return True


class _DelegationTracker:
    """Bounded registry of delegations started by this process."""

    def __init__(self, limit: int = _MAX_TRACKED):
        self._entries: "OrderedDict[str, _Delegation]" = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def add(self, delegation: _Delegation) -> None:
        with self._lock:
            self._entries[delegation.run_id] = delegation
            while len(self._entries) > self._limit:
                # Drop the oldest finished entry; never evict live work, whose
                # waiter still holds the only reference to its event.
                victim = next(
                    (
                        key
                        for key, value in self._entries.items()
                        if value.status in _TERMINAL
                    ),
                    None,
                )
                if victim is None:
                    break
                self._entries.pop(victim, None)

    def get(self, run_id: str) -> Optional[_Delegation]:
        with self._lock:
            return self._entries.get(run_id)


_tracker = _DelegationTracker()


class AgentDelegateTool(BaseTool):
    """Ask another registered Agent to complete a bounded subtask."""

    name = "agent_delegate"
    description = (
        "List peer Agents, hand one a concrete subtask, or check on a subtask "
        "you already handed over. A delegated target runs in its own workspace "
        "with its own memory, skills, sessions, and scheduler; its result comes "
        "back to you and is never sent to the user directly. Every delegation "
        "returns a run_id. Work that outlives your wait keeps running in the "
        "background, so use action='check' with that run_id to collect it later "
        "instead of asking again."
    )
    params = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "delegate", "check", "cancel"],
                "description": (
                    "list: discover targets. delegate: hand over a subtask. "
                    "check: read the state of a run_id. cancel: stop one."
                ),
                "default": "delegate",
            },
            "agent_id": {
                "type": "string",
                "description": "Target Agent ID for action='delegate'",
            },
            "task": {
                "type": "string",
                "description": "A self-contained task for the target Agent",
            },
            "run_id": {
                "type": "string",
                "description": "Delegation handle, for action='check' or 'cancel'",
            },
            "wait_seconds": {
                "type": "number",
                "description": (
                    "How long to wait inline before handing back a run_id. "
                    "Use 0 to return the handle immediately."
                ),
            },
        },
        "required": [],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.agent_bridge = None
        self.current_context = None

    def _policy(self) -> DelegationPolicy:
        if self.config:
            return DelegationPolicy.from_config(self.config)
        from config import conf

        return DelegationPolicy.from_config(conf().get("agent_delegation", {}))

    @staticmethod
    def _session_id(
        source_agent_id: str, target_agent_id: str, root_session_id: str
    ) -> str:
        digest = hashlib.sha256(root_session_id.encode("utf-8")).hexdigest()[:16]
        return f"delegate_{source_agent_id}_{target_agent_id}_{digest}"

    def execute(self, params: dict) -> ToolResult:
        if self.agent_bridge is None or self.current_context is None:
            return ToolResult.fail("Agent delegation is not attached to this turn")

        try:
            policy = self._policy()
        except (TypeError, ValueError) as exc:
            return ToolResult.fail(f"Invalid delegation policy: {exc}")
        if not policy.enabled:
            return ToolResult.fail("Agent delegation is disabled")
        context_values = dict(self.current_context.kwargs)
        source_agent_id = context_values.get("agent_id")
        if not source_agent_id:
            return ToolResult.fail("Source Agent could not be resolved")
        try:
            source = self.agent_bridge.agent_registry.get(source_agent_id)
        except (KeyError, ValueError):
            return ToolResult.fail(f"Source Agent '{source_agent_id}' is not available")

        action = params.get("action", "delegate")
        if action == "list":
            available = [
                {"id": profile.id, "name": profile.name}
                for profile in self.agent_bridge.agent_registry.list(
                    include_disabled=False
                )
                if policy.allows(source.id, profile.id)
            ]
            return ToolResult.success({"source_agent_id": source.id, "agents": available})
        if action == "check":
            return self._check(params.get("run_id"), source.id)
        if action == "cancel":
            return self._cancel(params.get("run_id"), source.id)
        if action != "delegate":
            return ToolResult.fail(f"Unsupported delegation action: {action}")
        return self._delegate(params, policy, source, context_values)

    def _delegate(
        self,
        params: dict,
        policy: DelegationPolicy,
        source,
        context_values: dict,
    ) -> ToolResult:
        target_agent_id = (params.get("agent_id") or "").strip()
        task = (params.get("task") or "").strip()
        if not target_agent_id or not task:
            return ToolResult.fail("agent_id and task are required for delegation")
        if len(task) > policy.max_message_chars:
            return ToolResult.fail(
                f"Delegated task exceeds {policy.max_message_chars} characters"
            )
        try:
            target = self.agent_bridge.agent_registry.get(target_agent_id)
        except (KeyError, ValueError):
            return ToolResult.fail(f"Target Agent '{target_agent_id}' is not available")

        raw_trace = context_values.get("delegation_trace") or (source.id,)
        if not isinstance(raw_trace, (list, tuple)) or not all(
            isinstance(item, str) for item in raw_trace
        ):
            return ToolResult.fail("Delegation trace is invalid")
        trace = tuple(raw_trace)
        if not trace or trace[-1] != source.id:
            return ToolResult.fail("Delegation trace does not match the source Agent")
        if target.id in trace:
            return ToolResult.fail(
                f"Delegation cycle rejected: {' -> '.join((*trace, target.id))}"
            )
        if not policy.allows(source.id, target.id):
            return ToolResult.fail(
                f"Agent '{source.id}' is not allowed to delegate to '{target.id}'"
            )

        depth = int(context_values.get("delegation_depth", len(trace) - 1)) + 1
        if depth > policy.max_depth:
            return ToolResult.fail(
                f"Delegation depth {depth} exceeds the maximum {policy.max_depth}"
            )

        try:
            wait_seconds = self._wait_seconds(params, policy)
        except (TypeError, ValueError):
            return ToolResult.fail("wait_seconds must be a non-negative number")

        root_session_id = str(
            context_values.get("delegation_root_session")
            or context_values.get("session_id")
            or uuid.uuid4()
        )
        session_id = self._session_id(source.id, target.id, root_session_id)
        request_id = f"delegate_{uuid.uuid4().hex}"

        # The handle is minted here, in the caller's thread, for two reasons:
        # it can be returned before the target has started, and the ambient run
        # id is only readable here -- context variables do not cross into the
        # worker thread below, so the parent link has to travel by value.
        from common.utils import current_agent_run_id

        run_id = uuid.uuid4().hex
        parent_run_id = current_agent_run_id() or ""

        delegated_context = Context(ContextType.TEXT, task, kwargs={})
        delegated_context["session_id"] = session_id
        delegated_context["request_id"] = request_id
        delegated_context["receiver"] = target.id
        delegated_context["isgroup"] = False
        delegated_context["channel_type"] = "agent"
        delegated_context["agent_id"] = target.id
        delegated_context["is_delegated_task"] = True
        delegated_context["delegated_by"] = source.id
        delegated_context["delegation_depth"] = depth
        delegated_context["delegation_trace"] = [*trace, target.id]
        delegated_context["delegation_root_session"] = root_session_id
        delegated_context["run_id"] = run_id
        delegated_context["parent_run_id"] = parent_run_id
        delegated_context["task_source"] = TASK_SOURCE

        prompt = (
            f"Delegated by Agent '{source.name}' ({source.id}).\n\n"
            f"Task:\n{task}\n\n"
            "Return a concise result to the delegating Agent. Do not address the user directly."
        )

        delegation = _Delegation(
            run_id=run_id,
            source_agent_id=source.id,
            target_agent_id=target.id,
            target_agent_name=target.name,
            session_id=session_id,
            request_id=request_id,
            depth=depth,
            timeout_seconds=policy.timeout_seconds,
        )
        _tracker.add(delegation)

        lock = _relay_lock(session_id)
        deadline = threading.Timer(
            policy.timeout_seconds, self._enforce_deadline, args=(delegation,)
        )
        deadline.daemon = True

        def run_target():
            acquired = lock.acquire(timeout=policy.timeout_seconds)
            if not acquired:
                self._settle(delegation, "failed", error="Target delegation session is busy")
                return
            try:
                reply = self.agent_bridge.agent_reply(
                    prompt, context=delegated_context, on_event=None
                )
                if reply is not None and reply.type == ReplyType.ERROR:
                    self._settle(delegation, "failed", error=str(reply.content))
                else:
                    content = reply.content if reply is not None else ""
                    self._settle(delegation, "done", content=content)
            except Exception as exc:
                self._settle(delegation, "failed", error=str(exc))
            finally:
                lock.release()
                deadline.cancel()

        deadline.start()
        threading.Thread(
            target=run_target,
            daemon=True,
            name=f"agent-delegate-{source.id}-{target.id}",
        ).start()

        started_at = time.monotonic()
        if wait_seconds > 0:
            delegation.done.wait(min(wait_seconds, policy.timeout_seconds))
        if delegation.status not in _TERMINAL:
            # Waiting all the way to the hard deadline is the caller asking us
            # to stop the target, not merely to stop listening.
            if time.monotonic() - started_at >= policy.timeout_seconds:
                self._enforce_deadline(delegation)
                deadline.cancel()
            else:
                return ToolResult.success(self._handle_payload(delegation))
        return self._outcome_payload(delegation)

    @staticmethod
    def _wait_seconds(params: dict, policy: DelegationPolicy) -> float:
        raw = params.get("wait_seconds")
        if raw is None or raw == "":
            return policy.default_wait_seconds
        value = float(raw)
        if value < 0:
            raise ValueError("wait_seconds must not be negative")
        return value

    def _settle(
        self, delegation: _Delegation, status: str, content: Any = None, error: str = ""
    ) -> None:
        """Land the outcome in memory and attach the payload to the run.

        The payload is persisted even when the handle already settled, so a
        target that answers after its deadline does not lose the result it
        produced. Only extras are written: a run's status belongs to whoever
        executed it, and having two writers fight over that field is how a
        cancelled run ends up claiming it succeeded.
        """
        delegation.settle(status, content=content, error=error)
        extras: Dict[str, Any] = {"delegated_by": delegation.source_agent_id}
        if content is not None:
            extras["result"] = content
        if error:
            extras["delegation_error"] = error
        try:
            store = self.agent_bridge.get_conversation_store(delegation.target_agent_id)
            store.update_run_extras(delegation.run_id, extras)
        except Exception as exc:
            logger.warning(
                f"[AgentDelegate] Could not record result for {delegation.run_id}: {exc}"
            )

    def _enforce_deadline(self, delegation: _Delegation) -> None:
        if delegation.status in _TERMINAL:
            return
        delegation.deadline_exceeded = True
        logger.warning(
            f"[AgentDelegate] Timed out source={delegation.source_agent_id} "
            f"target={delegation.target_agent_id} run={delegation.run_id}"
        )
        self._request_cancel(delegation, "Delegation exceeded its time budget")

    def _request_cancel(self, delegation: _Delegation, reason: str) -> None:
        """Ask the target to stop and settle the handle as cancelled.

        Only the request is made here; the target records its own cancellation
        when it honours it, and keeps running if it does not.
        """
        if delegation.status in _TERMINAL:
            return
        try:
            from agent.protocol import get_cancel_registry

            cancel_key = self.agent_bridge._cancel_key(
                delegation.target_agent_id,
                delegation.request_id,
                self.agent_bridge.agent_registry.default_agent_id,
            )
            get_cancel_registry().cancel_request(cancel_key)
        except Exception as exc:
            logger.warning(f"[AgentDelegate] Could not cancel {delegation.run_id}: {exc}")
        delegation.settle("cancelled", error=reason)

    def _handle_payload(self, delegation: _Delegation) -> Dict[str, Any]:
        return {
            "run_id": delegation.run_id,
            "agent_id": delegation.target_agent_id,
            "agent_name": delegation.target_agent_name,
            "delegated_by": delegation.source_agent_id,
            "depth": delegation.depth,
            "session_id": delegation.session_id,
            "status": "running",
            "note": (
                "Still working. Call agent_delegate with action='check' and this "
                "run_id to collect the result; do not delegate the task again."
            ),
        }

    def _outcome_payload(self, delegation: _Delegation) -> ToolResult:
        if delegation.status == "done":
            return ToolResult.success(
                {
                    "run_id": delegation.run_id,
                    "agent_id": delegation.target_agent_id,
                    "agent_name": delegation.target_agent_name,
                    "delegated_by": delegation.source_agent_id,
                    "depth": delegation.depth,
                    "session_id": delegation.session_id,
                    "status": "done",
                    "content": delegation.content,
                }
            )
        if delegation.status == "cancelled":
            if delegation.deadline_exceeded:
                return ToolResult.fail(
                    f"Delegation to '{delegation.target_agent_id}' timed out after "
                    f"{delegation.timeout_seconds:g} seconds"
                )
            return ToolResult.fail(
                f"Delegation to '{delegation.target_agent_id}' was cancelled: "
                f"{delegation.error}"
            )
        return ToolResult.fail(
            f"Delegation to '{delegation.target_agent_id}' failed: {delegation.error}"
        )

    def _locate(self, run_id: str):
        """Resolve a handle to (delegation, run row). Either may be None: the
        memory entry is gone after a restart, and the row is missing when run
        bookkeeping was unavailable.
        """
        delegation = _tracker.get(run_id)
        candidates = []
        if delegation is not None:
            candidates.append(delegation.target_agent_id)
        else:
            candidates.extend(
                profile.id
                for profile in self.agent_bridge.agent_registry.list(
                    include_disabled=True
                )
            )
        for agent_id in candidates:
            try:
                row = self.agent_bridge.get_conversation_store(agent_id).get_run(run_id)
            except Exception:
                continue
            if row:
                return delegation, row
        return delegation, None

    def _check(self, run_id: Optional[str], source_agent_id: str) -> ToolResult:
        run_id = (run_id or "").strip()
        if not run_id:
            return ToolResult.fail("run_id is required for action='check'")
        delegation, row = self._locate(run_id)
        if delegation is None and row is None:
            return ToolResult.fail(f"Unknown delegation handle '{run_id}'")
        # A handle is only readable by the Agent that created it, otherwise
        # peers could enumerate each other's work through guessed run ids.
        if delegation is not None and delegation.source_agent_id != source_agent_id:
            return ToolResult.fail(f"Unknown delegation handle '{run_id}'")
        if row is not None and row.get("task_source") != TASK_SOURCE:
            return ToolResult.fail(f"Run '{run_id}' is not a delegation")

        extras = (row or {}).get("extras") or {}
        # The executing side owns the status, so prefer the row and fall back to
        # the in-memory view only when no run was recorded.
        status = (row or {}).get("status") or (
            delegation.status if delegation else "unknown"
        )
        payload: Dict[str, Any] = {
            "run_id": run_id,
            "status": status,
            "agent_id": (row or {}).get("agent_id")
            or (delegation.target_agent_id if delegation else ""),
        }
        if delegation is not None:
            payload["agent_name"] = delegation.target_agent_name
            payload["delegated_by"] = delegation.source_agent_id
            payload["depth"] = delegation.depth
        if status not in _TERMINAL:
            payload["note"] = "Still working. Check again later."
            return ToolResult.success(payload)

        content = extras.get("result")
        if content is None and delegation is not None:
            content = delegation.content
        error = (
            extras.get("delegation_error")
            or (row or {}).get("error")
            or (delegation.error if delegation else "")
        )
        if status == "done":
            payload["content"] = content
            return ToolResult.success(payload)
        return ToolResult.fail(f"Delegation '{run_id}' ended as {status}: {error}")

    def _cancel(self, run_id: Optional[str], source_agent_id: str) -> ToolResult:
        run_id = (run_id or "").strip()
        if not run_id:
            return ToolResult.fail("run_id is required for action='cancel'")
        delegation = _tracker.get(run_id)
        if delegation is None or delegation.source_agent_id != source_agent_id:
            return ToolResult.fail(f"Unknown delegation handle '{run_id}'")
        if delegation.status in _TERMINAL:
            return ToolResult.success(
                {"run_id": run_id, "status": delegation.status, "cancelled": False}
            )
        self._request_cancel(delegation, f"Cancelled by Agent '{source_agent_id}'")
        return ToolResult.success(
            {"run_id": run_id, "status": delegation.status, "cancelled": True}
        )


def attach_agent_delegate_to_tool(tool, agent_bridge, context: Context) -> None:
    """Bind the current source turn and bridge to a delegation tool instance."""

    tool.agent_bridge = agent_bridge
    tool.current_context = context
