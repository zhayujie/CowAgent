"""Who a team message names, and the roster it is matched against.

Shared by every channel that supports team conversations (Web console, Feishu,
...). A message that starts with ``@name`` hands that turn to the named
teammate; the matcher is channel-agnostic so the rule reads the same in a
browser and in an IM group.
"""

from __future__ import annotations

import re
from typing import List, Optional

from common.log import logger


def roster_from_members(host_agent_id: str, members) -> List[dict]:
    """Everyone reachable in a conversation as ``{id, name}``, host first.

    Members arrive as the ids a caller may address an Agent by, so the reserved
    "default" alias is resolved here too. A member invited by alias is a member:
    reading it with ``get`` instead would raise on the alias, drop the entry as
    unknown, and leave an agent the user can see in the conversation
    unaddressable — with no error to explain why ``@default`` did nothing.

    Empty when there is no team (no members): a solo conversation names nobody.
    Unknown/disabled ids are dropped so the roster only holds addressable Agents.
    """
    if not members:
        return []
    from agent.multiagent import peer as peer_of
    from agent.registry import get_agent_registry

    registry = get_agent_registry()
    roster: List[dict] = []
    seen: set = set()
    for agent_id in [host_agent_id, *members]:
        if not agent_id:
            continue
        try:
            profile = registry.get_addressed(agent_id, require_enabled=False)
            entry = {"id": profile.id, "name": profile.name or profile.id}
        except Exception:
            # A teammate that runs elsewhere is still on the team: name it here
            # so "@name" reaches it like any other. None when nobody knows the
            # id, which stays dropped as before.
            found = peer_of(agent_id)
            if found is None:
                continue
            entry = {"id": found.id, "name": found.name or found.id}
        # Keyed on the resolved id, not the input: an alias and the id it
        # resolves to are one teammate and must not both reach the roster.
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        roster.append(entry)
    return roster


def addressed_agent_id(text: str, roster: List[dict]) -> str:
    """The teammate a message names, or "" when it names nobody.

    Matching accepts the display name as well as the id, because people write
    the name — nobody types ``@agent-17n3e8`` on purpose. Longer labels are
    tried first so a name containing another name still resolves to the one
    actually written.

    Only a leading mention counts. Naming somebody mid-sentence is usually
    talking *about* them ("ask Ops to..."), not handing them the turn.
    """
    stripped = (text or "").lstrip()
    if not stripped.startswith("@") or not roster:
        return ""
    candidates = []
    for item in roster:
        for label in (item.get("name") or "", item.get("id") or ""):
            if label:
                candidates.append((label, item["id"]))
    for label, agent_id in sorted(candidates, key=lambda pair: -len(pair[0])):
        pattern = r"^@" + re.escape(label) + r"(?=[\s，,：:、]|$)"
        if re.match(pattern, stripped, re.IGNORECASE):
            return agent_id
    return ""


def stamp_speaker_from_channel(channel, context, text) -> None:
    """Set ``context["speaker_agent_id"]`` when a team message names a teammate.

    A team channel instance carries its owner (``bound_agent_id``) plus
    ``members``; a leading ``@teammate`` in *text* hands this turn to that
    teammate, exactly like the Web console. Resolved from the instance roster
    directly so it works on the very first message, before ``session_prefs`` is
    seeded. A no-op for a solo bot (no members) or when nobody is named, so it
    is safe to call on every inbound message from any channel.
    """
    try:
        members = getattr(channel, "members", None)
        if not members or context is None:
            return
        owner = getattr(channel, "bound_agent_id", "") or ""
        roster = roster_from_members(owner, members)
        named = addressed_agent_id(text, roster)
        if named and named != owner:
            context["speaker_agent_id"] = named
    except Exception as e:
        logger.debug(f"[TeamAddressing] stamp_speaker failed: {e}")


def resolve_addressed_from_context(context, host_agent_id: str, query: str) -> Optional[str]:
    """The teammate a channel message addresses, using the session's team.

    Reads the conversation roster from the seeded ``session_prefs.members`` (the
    channel instance's team, materialized onto the session), then matches a
    leading ``@name`` in *query*. Returns "" when nobody is named or there is no
    team. Safe to call on every inbound message.
    """
    try:
        from agent.workspace import session_prefs

        session_id = ""
        if context is not None:
            session_id = context.get("session_id") or context.kwargs.get("session_id") or ""
        if not session_id:
            return ""
        members = session_prefs.get_prefs(session_id, host_agent_id).get("members")
        roster = roster_from_members(host_agent_id, members)
        return addressed_agent_id(query, roster)
    except Exception as e:
        logger.debug(f"[TeamAddressing] resolve failed: {e}")
        return ""
