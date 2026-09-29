"""Synchronous delegation between independently configured agent workspaces."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from agent.tools.base_tool import BaseTool, ToolResult
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from common.log import logger

# Marks delegated runs so they can be told apart from turns a user started.
TASK_SOURCE = "delegation"


def delegated_prompt(source_name: str, source_id: str, task: str) -> str:
    """What the teammate is actually asked. Shared with the path that serves
    a hand-off arriving from another process, so both read identically."""
    return (
        f"Delegated by Agent '{source_name}' ({source_id}).\n\n"
        f"Task:\n{task}\n\n"
        "Return a concise result to the delegating Agent. Do not address the user directly."
    )


def delegated_result_text(reply) -> str:
    """The teammate's answer as text for the delegating Agent.

    A teammate that sent files comes back as a file reply whose ``content``
    is the first file's URL; its prose rides in ``text_content``. Returning
    ``content`` alone would hand back a bare link and drop the answer.
    """
    if reply is None:
        return ""
    if reply.type not in (ReplyType.IMAGE_URL, ReplyType.FILE):
        return reply.content or ""
    parts = [getattr(reply, "text_content", "") or ""]
    for r in [reply] + list(getattr(reply, "extra_replies", None) or []):
        url = str(r.content or "")
        if not url:
            continue
        # Only a published image renders inline; a local path stays as it was.
        is_web = url.lower().startswith(("http://", "https://"))
        parts.append(f"![]({url})" if r.type == ReplyType.IMAGE_URL and is_web else url)
    return "\n\n".join(p for p in parts if p)


def format_delegate_result(
    source_name: str,
    target_name: str,
    content: str,
    status: str = "done",
    duration_seconds: float = 0,
) -> str:
    """The delegation's outcome, written for a person.

    The tool returns JSON for the delegating model to parse, but whoever is
    watching wants to see who handed what to whom and read the teammate's
    answer as prose, not a JSON blob. So the same outcome goes out a second
    time as markdown: a "source → target" heading and the teammate's reply
    (which is itself markdown), exactly the shape the sub agent report uses.
    """
    from agent.tools.subagent.subagent import _format_duration

    heading = f"{source_name} → {target_name}"
    if duration_seconds:
        heading += f" · {_format_duration(duration_seconds)}"
    body = content or "(no output)"
    if status != "done":
        body = f"**{status}** — {body}"
    return f"### {heading}\n\n{body}"


class _DelegateView:
    """What someone following the run sees of one delegation call.

    The delegating Agent's context is unaffected: it still receives only the
    teammate's returned result, which is the whole point. This is the other
    audience — the person watching — for whom a teammate that reports nothing
    until it finishes is indistinguishable from one that hung.

    So the teammate's turn is relayed as its own turn: the events are passed
    through untouched, bracketed by a start/end pair naming who is speaking.
    A client that understands the pair attributes them to the teammate and
    renders them exactly as it renders any other reply; one that does not
    still has the delegation result on the call's card, as before. Without
    that attribution the prose would read as the delegating Agent suddenly
    talking about someone else's work, which is why it used to be dropped.
    """

    #: A teammate's turn looks like any other: prose, reasoning, tool calls.
    RELAYED = (
        "message_update",
        "reasoning_update",
        "tool_execution_start",
        "tool_execution_progress",
        "tool_execution_end",
    )

    #: Emitted around a relayed turn to say who it belongs to.
    START = "peer_message_start"
    END = "peer_message_end"

    def __init__(self, tool, card_id: str, source, target_id: str, target_name: str):
        self.tool = tool
        self.card_id = card_id
        self.source_id = getattr(source, "id", "") or ""
        self.source_name = getattr(source, "name", "") or self.source_id
        self.target_id = target_id
        self.target_name = target_name or target_id
        self._open = False

    def relay(self, event: dict) -> None:
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        data = event.get("data") or {}
        # A teammate handing work onward is still just another turn: pass its
        # markers up untouched so the chain reads as a flat sequence of turns
        # rather than turns nested inside turns.
        if event_type in (self.START, self.END):
            self.tool.emit_event(event_type, data)
            return
        if event_type not in self.RELAYED:
            return
        self.open()
        self.tool.emit_event(event_type, data)

    def open(self) -> None:
        """Announce the teammate's turn, once, when it first has something to say."""
        if self._open:
            return
        self._open = True
        self.tool.emit_event(
            self.START,
            {
                "card_id": self.card_id,
                "agent_id": self.target_id,
                "agent_name": self.target_name,
                "source_id": self.source_id,
                "source_name": self.source_name,
            },
        )

    def close(self, status: str = "done") -> None:
        """End the teammate's turn, so what follows is the caller speaking again."""
        if not self._open:
            return
        self._open = False
        self.tool.emit_event(
            self.END,
            {"card_id": self.card_id, "agent_id": self.target_id, "status": status},
        )


@dataclass(frozen=True)
class DelegationPolicy:
    enabled: bool = True
    allowed_targets: Optional[Mapping[str, Tuple[str, ...]]] = None
    max_depth: int = 3
    timeout_seconds: float = 600.0
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
        timeout_seconds = float(raw.get("timeout_seconds", 600))
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


# One delegated target answers one turn at a time within a conversation, so
# concurrent hands-offs to the same relay session queue behind this lock rather
# than interleaving in the target's transcript.
_relay_locks = {}
_relay_locks_guard = threading.Lock()


def _relay_lock(session_id: str) -> threading.Lock:
    with _relay_locks_guard:
        return _relay_locks.setdefault(session_id, threading.Lock())


class AgentDelegateTool(BaseTool):
    """Hand a bounded subtask to a teammate in this team conversation."""

    name = "agent_delegate"
    description = (
        "Delegate a task to a teammate in this team conversation and wait for "
        "its result. The teammates you can delegate to, and their IDs, are the "
        "ones listed in the team conversation section of your context. The "
        "teammate works in its own workspace and returns a result to you."
    )
    params = {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": (
                    "The teammate's Agent ID (the @id shown for them in the team "
                    "conversation section)."
                ),
            },
            "task": {
                "type": "string",
                "description": (
                    "A self-contained task for the teammate, with everything it "
                    "needs to act without seeing this conversation."
                ),
            },
        },
        "required": ["agent_id", "task"],
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

    def _team_members(self, context_values: dict, source_agent_id: str) -> list:
        """The teammates the source Agent may delegate to this turn.

        Exactly the roster the "team conversation" prompt section lists: the
        conversation's host plus its members, minus the source itself and
        anyone the ACL forbids. Delegation is bounded to the people the Agent
        was actually told it is working with, so it can never hand work to an
        Agent outside the room. Returns ``[{id, name}]`` so an error can name
        the real options.

        The host is included because a guest answering the turn (the user
        addressed a teammate by name) is not the conversation owner, yet the
        prompt lists the owner as one of its teammates. Leaving the host out
        here — while the prompt keeps it in — is exactly what makes the model
        hand work to the host and the tool reject it. ``agent_id`` on the turn
        context is the conversation owner (routing overwrites it with the
        host), so it is the host from the guest's point of view.

        On a delegated turn the source runs in its own private session, which
        carries no ``members`` of its own; the original team's roster rides
        down the chain in the context instead (``delegation_members``), so a
        teammate can hand work onward to the same team, not just answer.
        """
        members = context_values.get("delegation_members")
        host_id = None
        if not members:
            session_id = str(
                context_values.get("delegation_root_session")
                or context_values.get("session_id")
                or ""
            )
            if not session_id:
                return []
            # The conversation owner (host). On a user-facing turn routing has
            # overwritten ``agent_id`` with the host, so it names the owner even
            # when a guest is the one speaking. Members are stored under the
            # host, so read them with the host id, not the speaking source.
            host_id = context_values.get("agent_id") or source_agent_id
            try:
                from agent.workspace import session_prefs

                members = session_prefs.get_prefs(session_id, host_id).get(
                    "members"
                )
            except Exception as exc:
                logger.warning(f"[AgentDelegate] Could not read team members: {exc}")
                return []

        policy = self._policy_safe()
        roster = []
        # The host is a delegable teammate too, listed first to match the prompt
        # roster ([host, *members]). A delegated (nested) turn skips this: there
        # is no user-facing host, and ``delegation_members`` already carries the
        # reachable team down the chain.
        candidate_ids = list(members or [])
        if host_id and host_id not in candidate_ids:
            candidate_ids.insert(0, host_id)
        for member_id in candidate_ids:
            if not member_id or member_id == source_agent_id:
                continue
            if policy is not None and not policy.allows(source_agent_id, member_id):
                continue
            # A teammate may be hosted in another process; the roster lists it
            # the same way, and the hand-off itself picks the route later.
            from agent.multiagent import resolve_teammate

            entry = resolve_teammate(member_id, self.agent_bridge.agent_registry)
            if entry is None:
                continue
            if any(item["id"] == entry["id"] for item in roster):
                continue
            roster.append({"id": entry["id"], "name": entry["name"]})
        return roster

    def _policy_safe(self) -> Optional[DelegationPolicy]:
        try:
            return self._policy()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _roster_hint(roster: list) -> str:
        """One-line "who you can actually delegate to" for an error message."""
        if not roster:
            return "There are no teammates you can delegate to in this conversation."
        names = ", ".join(f"{item['name']} ({item['id']})" for item in roster)
        return f"Teammates you can delegate to: {names}."

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
        # The source is whoever is actually answering this turn. When the user
        # addressed a teammate by name, that guest (``speaker_agent_id``) is
        # speaking, not the conversation owner — routing overwrote ``agent_id``
        # with the host, so using it here would delegate under the host's
        # identity and reject the guest handing work to the host. Fall back to
        # ``agent_id`` for a delegated (nested) turn, which carries no speaker.
        source_agent_id = (
            context_values.get("speaker_agent_id") or context_values.get("agent_id")
        )
        if not source_agent_id:
            return ToolResult.fail("Source Agent could not be resolved")
        try:
            source = self.agent_bridge.agent_registry.get(source_agent_id)
        except (KeyError, ValueError):
            return ToolResult.fail(f"Source Agent '{source_agent_id}' is not available")

        roster = self._team_members(context_values, source.id)
        return self._delegate(params, policy, source, context_values, roster)

    def _delegate(
        self,
        params: dict,
        policy: DelegationPolicy,
        source,
        context_values: dict,
        roster: list,
    ) -> ToolResult:
        # The roster shows ids as "@id", so a model often passes the "@" too.
        # Strip it rather than reject a correct target on a cosmetic prefix.
        target_agent_id = (params.get("agent_id") or "").strip().lstrip("@")
        task = (params.get("task") or "").strip()
        if not target_agent_id or not task:
            return ToolResult.fail("agent_id and task are required for delegation")
        if len(task) > policy.max_message_chars:
            return ToolResult.fail(
                f"Delegated task exceeds {policy.max_message_chars} characters"
            )
        # The target must be a teammate in this conversation, not just any Agent
        # the ACL would allow: delegation stays inside the team the user set up.
        # Name the real options so the model can correct itself in one step
        # rather than guessing again.
        if target_agent_id not in {item["id"] for item in roster}:
            return ToolResult.fail(
                f"'{target_agent_id}' is not a teammate you can delegate to in this "
                f"conversation. {self._roster_hint(roster)}"
            )
        # The teammate is either an Agent of this process or one reached over
        # the installed transport. Everything up to the actual run treats the
        # two alike, so the guards below apply to both.
        from agent.multiagent import get_transport, peer as peer_of

        target = None
        peer_target = None
        try:
            target = self.agent_bridge.agent_registry.get(target_agent_id)
        except (KeyError, ValueError):
            peer_target = peer_of(target_agent_id)
            if peer_target is None or get_transport() is None:
                return ToolResult.fail(f"Target Agent '{target_agent_id}' is not available")
        target_id = target.id if target is not None else peer_target.id

        raw_trace = context_values.get("delegation_trace") or (source.id,)
        if not isinstance(raw_trace, (list, tuple)) or not all(
            isinstance(item, str) for item in raw_trace
        ):
            return ToolResult.fail("Delegation trace is invalid")
        trace = tuple(raw_trace)
        if not trace or trace[-1] != source.id:
            return ToolResult.fail("Delegation trace does not match the source Agent")
        if target_id in trace:
            return ToolResult.fail(
                f"Delegation cycle rejected: {' -> '.join((*trace, target_id))}"
            )
        if not policy.allows(source.id, target_id):
            return ToolResult.fail(
                f"Agent '{source.id}' is not allowed to delegate to '{target_id}'"
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
        # The team the teammate may hand work onward to: this conversation's
        # roster plus whatever rode down the chain, minus those already in it.
        team_ids = {source.id, *(item["id"] for item in roster)}
        team_ids |= set(context_values.get("delegation_members") or [])
        onward_members = sorted(team_ids - set(trace))

        # The run id is minted here and carried by value: the target may run
        # under a different ambient run id, but linking the child to this parent
        # keeps the run tree walkable from either end.
        from common.utils import current_agent_run_id

        run_id = uuid.uuid4().hex
        parent_run_id = current_agent_run_id() or ""

        # Relay the teammate's turn as it happens so a watcher can follow the
        # delegated work live. The card is this tool call, since one delegation
        # is one card.
        card_id = getattr(self, "tool_call_id", None) or run_id
        speaker = target if target is not None else peer_target
        view = _DelegateView(
            self, card_id, source,
            getattr(speaker, "id", "") or "",
            getattr(speaker, "name", "") or "",
        )

        if target is None:
            return self._delegate_peer(
                source, peer_target, task, policy, trace, depth,
                root_session_id, onward_members, view, run_id,
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
        # Carry the original team's roster down the chain so the teammate can
        # hand work onward to the same team — its private delegated session has
        # no members of its own. The source itself is included so a later hop
        # could reach it; the cycle guard, not the roster, stops loops. The
        # source drops whoever is already in the chain to prompt only reachable
        # options.
        delegated_context["delegation_members"] = onward_members
        delegated_context["run_id"] = run_id
        delegated_context["parent_run_id"] = parent_run_id
        delegated_context["task_source"] = TASK_SOURCE

        prompt = delegated_prompt(source.name, source.id, task)

        # Serialize hands-off to the same target session, then run it inline:
        # the caller waits for the teammate's answer and returns it directly.
        lock = _relay_lock(session_id)
        if not lock.acquire(timeout=policy.timeout_seconds):
            display = format_delegate_result(
                source.name, target.name, "timed out waiting for the teammate to be free",
                status="failed",
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' timed out waiting for the target to be free",
                display=display,
            )
        started_at = time.monotonic()
        try:
            reply = self.agent_bridge.agent_reply(
                prompt, context=delegated_context, on_event=view.relay
            )
        except Exception as exc:
            display = format_delegate_result(
                source.name, target.name, str(exc), status="failed"
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' failed: {exc}", display=display
            )
        finally:
            # Whatever happened, the teammate is done speaking.
            view.close()
            lock.release()
        duration = time.monotonic() - started_at

        if reply is not None and reply.type == ReplyType.ERROR:
            display = format_delegate_result(
                source.name, target.name, str(reply.content), status="failed",
                duration_seconds=duration,
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' failed: {reply.content}", display=display
            )
        content = delegated_result_text(reply)
        display = format_delegate_result(
            source.name, target.name, content, status="done", duration_seconds=duration,
        )
        return ToolResult.success(
            {
                "run_id": run_id,
                "agent_id": target.id,
                "agent_name": target.name,
                "delegated_by": source.id,
                "depth": depth,
                "session_id": session_id,
                "status": "done",
                "content": content,
            },
            display=display,
        )

    def _delegate_peer(
        self, source, target, task: str, policy: DelegationPolicy, trace: tuple,
        depth: int, root_session_id: str, onward_members: list,
        view: "_DelegateView", run_id: str,
    ) -> ToolResult:
        """Hand the task to a teammate hosted in another process.

        Same guards, same card, same result shape as a local hand-off; only
        the run happens elsewhere. The teammate is sent the whole team as
        profiles so it can name them on its own roster and hand work onward.
        """
        from agent.multiagent import InvokeRequest, PeerAgent, get_transport, resolve_teammate

        transport = get_transport()
        if transport is None:
            return ToolResult.fail(f"Target Agent '{target.id}' is not available")

        peers = []
        for member_id in onward_members:
            entry = resolve_teammate(member_id, self.agent_bridge.agent_registry)
            if entry is not None:
                peers.append(PeerAgent.from_any(entry))
        request = InvokeRequest(
            request_id=f"delegate_{uuid.uuid4().hex}",
            target_id=target.id,
            task=task,
            source_id=source.id,
            source_name=source.name,
            root_session_id=root_session_id,
            trace=(*trace, target.id),
            depth=depth,
            members=tuple(onward_members),
            peers=tuple(p for p in peers if p is not None),
            timeout_seconds=policy.timeout_seconds,
        )
        started_at = time.monotonic()
        try:
            result = transport.invoke(request, on_event=view.relay)
        except Exception as exc:
            display = format_delegate_result(source.name, target.name, str(exc), status="failed")
            return ToolResult.fail(f"Delegation to '{target.id}' failed: {exc}", display=display)
        finally:
            # Whatever happened, the teammate is done speaking.
            view.close()
        duration = result.duration_seconds or (time.monotonic() - started_at)

        if not result.ok:
            display = format_delegate_result(
                source.name, target.name, result.error, status="failed", duration_seconds=duration,
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' failed: {result.error}", display=display
            )
        display = format_delegate_result(
            source.name, target.name, result.content, status="done", duration_seconds=duration,
        )
        return ToolResult.success(
            {
                "run_id": run_id,
                "agent_id": target.id,
                "agent_name": result.agent_name or target.name,
                "delegated_by": source.id,
                "depth": depth,
                "status": "done",
                "content": result.content,
            },
            display=display,
        )


def attach_agent_delegate_to_tool(tool, agent_bridge, context: Context) -> None:
    """Bind the current source turn and bridge to a delegation tool instance."""

    tool.agent_bridge = agent_bridge
    tool.current_context = context
