"""Shared plumbing for the team collaboration tools.

``team_send`` / ``team_inbox`` / ``team_task`` all work against the same
shared team runtime (:mod:`agent.team_runtime`). What they need beyond the
store is turn identity — who is speaking, which conversation is the team,
who else is in it — and, for ``team_send``, the ability to wake a teammate
so a stored message becomes a live turn. This module owns both, so the
three tools stay thin.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from typing import List, Optional

from agent.team_runtime import CollabPolicy, get_team_store
from bridge.context import Context, ContextType
from common.log import logger


def attach_team_collab_tools(tool, agent_bridge, context: Context) -> None:
    """Bind the current turn and bridge to a team tool instance.

    Mirrors ``attach_agent_delegate_to_tool``: called once per turn for
    every team tool the running Agent carries."""
    tool.agent_bridge = agent_bridge
    tool.current_context = context


class TeamCollabContext:
    """Turn identity for one team tool call.

    The roster is resolved the same way the "team conversation" prompt
    section builds it (host plus members), except the speaker is kept in
    the list too: the task board records who owns what, and the speaker may
    legitimately own a task. On a delegated or wake turn the roster rides
    down the chain in ``delegation_members`` instead of session prefs,
    exactly as agent_delegate does."""

    def __init__(self, tool, agent_bridge, context: Context):
        self.tool = tool
        self.bridge = agent_bridge
        self.context = context
        self.values = dict(getattr(context, "kwargs", {}) or {})
        self.store = get_team_store()

    @property
    def policy(self) -> CollabPolicy:
        try:
            from config import conf

            return CollabPolicy.from_config(conf().get("team_collab", {}) or {})
        except (ImportError, TypeError, ValueError):
            return CollabPolicy()

    @property
    def self_agent_id(self) -> str:
        # The speaker is whoever is answering this turn. When the user
        # addressed a teammate by name, that guest is speaking, not the
        # conversation owner — routing overwrote ``agent_id`` with the host,
        # so using it here would act under the host's identity (the same
        # rule agent_delegate follows).
        return str(
            self.values.get("speaker_agent_id")
            or self.values.get("agent_id")
            or ""
        )

    @property
    def self_name(self) -> str:
        agent_id = self.self_agent_id
        if not agent_id:
            return ""
        from agent.multiagent import resolve_teammate

        entry = resolve_teammate(agent_id, getattr(self.bridge, "agent_registry", None))
        if entry:
            return entry.get("name", "") or agent_id
        return agent_id

    @property
    def team_id(self) -> str:
        # The shared board belongs to the team conversation, not to the
        # private session a delegated or wake turn happens to run in.
        return str(
            self.values.get("delegation_root_session")
            or self.values.get("session_id")
            or ""
        )

    def roster(self) -> List[dict]:
        """``[{id, name}]`` for everyone in the team, speaker included."""
        members = self.values.get("delegation_members")
        host_id = None
        if not members:
            session_id = str(
                self.values.get("delegation_root_session")
                or self.values.get("session_id")
                or ""
            )
            if not session_id:
                return []
            # Members are stored under the conversation owner (host); on a
            # user-facing turn ``agent_id`` names the host even when a guest
            # is speaking.
            host_id = self.values.get("agent_id") or self.self_agent_id
            try:
                from agent.workspace import session_prefs

                members = session_prefs.get_prefs(session_id, host_id).get("members")
            except Exception as exc:
                logger.warning(f"[TeamCollab] Could not read team members: {exc}")
                members = []
        candidate_ids = [m for m in (members or []) if m]
        if host_id and host_id not in candidate_ids:
            candidate_ids.insert(0, host_id)
        if self.self_agent_id and self.self_agent_id not in candidate_ids:
            candidate_ids.append(self.self_agent_id)
        from agent.multiagent import resolve_teammate

        registry = getattr(self.bridge, "agent_registry", None)
        roster: List[dict] = []
        for member_id in candidate_ids:
            if not member_id or any(item["id"] == member_id for item in roster):
                continue
            entry = resolve_teammate(member_id, registry)
            if entry is None:
                if member_id == self.self_agent_id:
                    entry = {"id": member_id, "name": self.self_name or member_id}
                else:
                    continue
            if any(item["id"] == entry["id"] for item in roster):
                continue
            roster.append({"id": entry["id"], "name": entry.get("name", "") or entry["id"]})
        return roster

    def roster_hint(self) -> str:
        entries = ", ".join(f"{item['name']} ({item['id']})" for item in self.roster())
        return f"Team members: {entries}." if entries else "No teammates found."


# One wake session answers one message at a time, so simultaneous messages
# to the same teammate queue their turns instead of interleaving them.
_wake_locks = {}
_wake_locks_guard = threading.Lock()


def _wake_lock(session_id: str) -> threading.Lock:
    with _wake_locks_guard:
        return _wake_locks.setdefault(session_id, threading.Lock())


def wake_session_id(team_id: str, recipient_id: str) -> str:
    """Stable private session for one (team, recipient) pair.

    Stable so a teammate woken repeatedly for the same team keeps one warm
    context instead of starting every message from scratch."""
    digest = hashlib.sha256(str(team_id).encode("utf-8")).hexdigest()[:16]
    return f"team_{digest}_{recipient_id}"


def wake_prompt(from_name: str, from_id: str, team_hint: str, content: str) -> str:
    """What the woken teammate is actually asked, shared by both routes."""
    header = f"Team message from Agent '{from_name}' ({from_id})"
    if team_hint:
        header += f" in {team_hint}"
    return (
        f"{header}.\n\n{content}\n\n"
        "(The message is already in your team inbox; this turn exists so you "
        "can act on it now. Answer the team with team_send, or take the "
        "action asked of you and report back.)"
    )


def deliver_wakes(
    collab: "TeamCollabContext",
    recipients: List[dict],
    content: str,
    team_hint: str = "",
) -> dict:
    """Turn stored messages into live turns for the recipients.

    Store-side delivery, AionUi style: the mailbox record is the source of
    truth and a wake is a courtesy nudge on top. A teammate hosted here gets
    a private turn through ``agent_reply``; one hosted in another process
    gets a fire-and-forget peer invoke. Both run in background threads — the
    sending turn must not wait on its whole team.

    Depth is capped (``team_collab.max_wake_depth``): A wakes B, B answers
    with team_send, which wakes A... without a cap the team talks forever on
    its own. Waking is itself configurable off (``wake_on_message``).
    """
    policy = collab.policy
    if not policy.wake_on_message:
        return {"woken": [], "reason": "waking disabled (team_collab.wake_on_message)"}
    depth = int(collab.values.get("team_wake_depth", 0) or 0)
    if depth >= policy.max_wake_depth:
        return {
            "woken": [],
            "reason": f"wake chain reached max depth {policy.max_wake_depth}",
        }
    if not content:
        return {"woken": [], "reason": "nothing to deliver"}

    source_id = collab.self_agent_id
    source_name = collab.self_name or source_id
    team_id = collab.team_id
    roster_ids = [item["id"] for item in collab.roster()]
    prompt = wake_prompt(source_name, source_id, team_hint, content)
    registry = getattr(collab.bridge, "agent_registry", None)

    from agent.multiagent import InvokeRequest, get_transport, peer

    transport = get_transport()
    woken: List[dict] = []
    unreachable: List[str] = []
    for entry in recipients:
        recipient_id = entry["id"]
        if recipient_id == source_id:
            continue
        agent = None
        if registry is not None:
            try:
                agent = registry.get(recipient_id)
            except Exception:
                agent = None
        peer_target = peer(recipient_id) if agent is None else None
        if agent is None and (peer_target is None or transport is None):
            unreachable.append(recipient_id)
            continue
        # Who the woken teammate may talk to onward: the team minus itself.
        onward = sorted(set(roster_ids) - {recipient_id})
        if agent is not None:
            session_id = wake_session_id(team_id, recipient_id)
            wake_context = Context(ContextType.TEXT, prompt, kwargs={})
            wake_context["session_id"] = session_id
            wake_context["request_id"] = f"team_{uuid.uuid4().hex}"
            wake_context["receiver"] = agent.id
            wake_context["isgroup"] = False
            wake_context["channel_type"] = "agent"
            wake_context["agent_id"] = agent.id
            wake_context["is_delegated_task"] = True
            wake_context["delegated_by"] = source_id
            wake_context["delegation_root_session"] = team_id
            wake_context["delegation_members"] = onward
            wake_context["team_wake_depth"] = depth + 1
            thread = threading.Thread(
                target=_run_local_wake,
                args=(collab.bridge, wake_context),
                daemon=True,
                name=f"team-wake-{recipient_id}",
            )
        else:
            request = InvokeRequest(
                request_id=f"team_{uuid.uuid4().hex}",
                target_id=peer_target.id,
                task=prompt,
                source_id=source_id,
                source_name=source_name,
                root_session_id=team_id,
                trace=(source_id, peer_target.id),
                depth=1,
                members=tuple(onward),
            )
            thread = threading.Thread(
                target=_run_peer_wake,
                args=(transport, request),
                daemon=True,
                name=f"team-wake-{recipient_id}",
            )
        thread.start()
        woken.append({"id": recipient_id, "name": entry.get("name", "")})
    result = {"woken": woken}
    if unreachable:
        result["not_woken"] = unreachable
    return result


def _run_local_wake(bridge, wake_context: Context) -> None:
    session_id = wake_context.kwargs.get("session_id", "")
    with _wake_lock(str(session_id)):
        try:
            bridge.agent_reply(str(wake_context.content), wake_context)
        except Exception as exc:
            logger.warning(
                f"[TeamCollab] Wake turn failed for session {session_id}: {exc}"
            )


def _run_peer_wake(transport, request) -> None:
    try:
        transport.invoke(request)
    except Exception as exc:
        logger.warning(
            f"[TeamCollab] Peer wake to '{request.target_id}' failed: {exc}"
        )