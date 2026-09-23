"""Named teams: persistent, user-created groups of Agents.

The conversation-level team (who is in ONE session) lives in
:mod:`agent.workspace.session_prefs`; this is the layer above it. A named
team is a saved roster with a leader that the console lists in the sidebar
and can open as a group conversation any number of times. Records are plain
JSON under ``shared_root()`` — the same spirit as the scheduler store,
deliberately not per-Agent, because a team belongs to the person who
assembled it, not to any one of its members.

Two invariants, both borrowed from the group-chat conventions the rest of
the code already uses: the leader is always ``members[0]`` and can never be
dropped by a member update, and member ids are unique. Members are
validated against the Agent registry at the API layer; this module only
enforces its own shape.
"""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from common.log import logger
from common.state_dir import teams_registry_file

_lock = threading.RLock()


class TeamsStoreError(RuntimeError):
    """Raised when a payload cannot form a valid team."""


def _load(base=None) -> List[dict]:
    path = teams_registry_file(base)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (ValueError, OSError) as exc:
        logger.warning(f"[TeamsStore] could not read registry: {exc}")
        return []


def _save(teams: List[dict], base=None) -> None:
    path = teams_registry_file(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _ordered_ids(leader: str, members) -> List[str]:
    """Leader first, then the members in order, deduplicated."""
    ids: List[str] = []
    for candidate in [leader] + list(members or []):
        cid = str(candidate or "").strip()
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def list_teams(base=None) -> List[dict]:
    with _lock:
        teams = _load(base)
    return sorted(teams, key=lambda t: t.get("created_at", ""))


def get_team(team_id: str, base=None) -> dict:
    with _lock:
        for team in _load(base):
            if team.get("id") == team_id:
                return dict(team)
    raise KeyError(team_id)


def create_team(name, leader, members=None, base=None) -> dict:
    name = str(name or "").strip()
    if not name:
        raise TeamsStoreError("a team needs a name")
    leader = str(leader or "").strip()
    if not leader:
        raise TeamsStoreError("a team needs a leader")
    now = datetime.now().isoformat(timespec="seconds")
    team = {
        "id": "t_" + uuid.uuid4().hex[:10],
        "name": name,
        "leader": leader,
        "members": _ordered_ids(leader, members),
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        teams = _load(base)
        teams.append(team)
        _save(teams, base)
    return dict(team)


def update_team(team_id: str, name=None, leader=None, members=None, base=None) -> dict:
    """Update one team.

    ``members`` is the desired roster; the leader is kept even when the
    caller omits them (the leader can be re-placed but never dropped by a
    roster write), and the leader is always moved to ``members[0]``.
    """
    with _lock:
        teams = _load(base)
        for team in teams:
            if team.get("id") != team_id:
                continue
            if name is not None:
                name = str(name).strip()
                if not name:
                    raise TeamsStoreError("a team needs a name")
                team["name"] = name
            desired = (list(members) if members is not None
                       else list(team.get("members") or []))
            new_leader = (str(leader).strip() if leader is not None
                          else str(team.get("leader") or ""))
            if not new_leader:
                new_leader = desired[0] if desired else ""
            if not new_leader:
                raise TeamsStoreError("a team needs a leader")
            if new_leader not in desired:
                desired = [new_leader] + desired
            team["members"] = _ordered_ids(new_leader, desired)
            team["leader"] = team["members"][0]
            team["updated_at"] = datetime.now().isoformat(timespec="seconds")
            _save(teams, base)
            return dict(team)
    raise KeyError(team_id)


def delete_team(team_id: str, base=None) -> None:
    with _lock:
        teams = _load(base)
        remaining = [t for t in teams if t.get("id") != team_id]
        if len(remaining) == len(teams):
            raise KeyError(team_id)
        _save(remaining, base)