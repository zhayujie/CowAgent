"""Guarded delegation between independently configured agent workspaces."""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Mapping, Optional, Tuple

from agent.tools.base_tool import BaseTool, ToolResult
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from common.log import logger


@dataclass(frozen=True)
class DelegationPolicy:
    enabled: bool = True
    allowed_targets: Optional[Mapping[str, Tuple[str, ...]]] = None
    max_depth: int = 3
    timeout_seconds: float = 120.0
    max_message_chars: int = 8000

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
        if not 1 <= max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")
        if not 0.01 <= timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be between 0.01 and 600")
        if not 1 <= max_message_chars <= 100000:
            raise ValueError("max_message_chars must be between 1 and 100000")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            allowed_targets=normalized,
            max_depth=max_depth,
            timeout_seconds=timeout_seconds,
            max_message_chars=max_message_chars,
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


class AgentDelegateTool(BaseTool):
    """Ask another registered Agent to complete a bounded subtask."""

    name = "agent_delegate"
    description = (
        "List available peer Agents or delegate a concrete subtask to one. Use "
        "action='list' to discover targets. A delegated target runs in its own "
        "workspace with its own memory, skills, sessions, and scheduler. Its "
        "result is returned to you and is not sent directly to the user."
    )
    params = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "delegate"],
                "description": "List available targets or delegate a task",
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
        if action != "delegate":
            return ToolResult.fail(f"Unsupported delegation action: {action}")

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

        root_session_id = str(
            context_values.get("delegation_root_session")
            or context_values.get("session_id")
            or uuid.uuid4()
        )
        session_id = self._session_id(source.id, target.id, root_session_id)
        request_id = f"delegate_{uuid.uuid4().hex}"
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

        prompt = (
            f"Delegated by Agent '{source.name}' ({source.id}).\n\n"
            f"Task:\n{task}\n\n"
            "Return a concise result to the delegating Agent. Do not address the user directly."
        )
        result_queue = Queue(maxsize=1)
        lock = _relay_lock(session_id)

        def run_target():
            acquired = lock.acquire(timeout=policy.timeout_seconds)
            if not acquired:
                result_queue.put((False, "Target delegation session is busy"))
                return
            try:
                reply = self.agent_bridge.agent_reply(
                    prompt, context=delegated_context, on_event=None
                )
                result_queue.put((True, reply))
            except Exception as exc:
                result_queue.put((False, str(exc)))
            finally:
                lock.release()

        threading.Thread(
            target=run_target,
            daemon=True,
            name=f"agent-delegate-{source.id}-{target.id}",
        ).start()
        try:
            ok, value = result_queue.get(timeout=policy.timeout_seconds)
        except Empty:
            from agent.protocol import get_cancel_registry

            cancel_key = self.agent_bridge._cancel_key(
                target.id,
                request_id,
                self.agent_bridge.agent_registry.default_agent_id,
            )
            get_cancel_registry().cancel_request(cancel_key)
            logger.warning(
                f"[AgentDelegate] Timed out source={source.id} target={target.id}"
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' timed out after "
                f"{policy.timeout_seconds:g} seconds"
            )

        if not ok:
            return ToolResult.fail(f"Delegation to '{target.id}' failed: {value}")
        if value.type == ReplyType.ERROR:
            return ToolResult.fail(str(value.content))
        return ToolResult.success(
            {
                "agent_id": target.id,
                "agent_name": target.name,
                "delegated_by": source.id,
                "depth": depth,
                "session_id": session_id,
                "content": value.content,
            }
        )


def attach_agent_delegate_to_tool(tool, agent_bridge, context: Context) -> None:
    """Bind the current source turn and bridge to a delegation tool instance."""

    tool.agent_bridge = agent_bridge
    tool.current_context = context
