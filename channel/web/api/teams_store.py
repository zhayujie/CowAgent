"""Named teams API: create, list, edit and delete the console's saved Agent
groups (the sidebar "Teams" section).

Distinct from :mod:`channel.web.api.team`, which is the read-only view of
ONE team conversation's runtime state. This module owns the persistent
rosters themselves — a named team is opened as a group conversation and the
opened session's roster (``POST /api/sessions/<id>/settings`` members) is
seeded from it.
"""

import json

import web

from agent import teams_store
from channel.web.core._common import _require_auth
from common.log import logger


def _profile_view(registry, agent_id: str) -> dict:
    """``{id, name, available}`` for one member id."""
    try:
        profile = registry.get_addressed(agent_id, require_enabled=False)
        return {"id": profile.id, "name": profile.name or profile.id}
    except Exception:
        return {"id": agent_id, "name": agent_id, "available": False}


def _team_view(registry, team: dict) -> dict:
    return {
        "id": team["id"],
        "name": team.get("name", ""),
        "leader": team.get("leader", ""),
        "members": [_profile_view(registry, mid) for mid in team.get("members") or []],
        "created_at": team.get("created_at", ""),
        "updated_at": team.get("updated_at", ""),
    }


class TeamsStoreHandler:
    """``GET /api/team-groups`` lists teams; ``POST`` creates one."""

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.registry import get_agent_registry
            registry = get_agent_registry()
            teams = [_team_view(registry, t) for t in teams_store.list_teams()]
            return json.dumps({"status": "success", "teams": teams},
                              ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] team-groups list failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            team = teams_store.create_team(
                body.get("name"),
                body.get("leader"),
                body.get("members"),
            )
            from agent.registry import get_agent_registry
            registry = get_agent_registry()
            return json.dumps({"status": "success", "team": _team_view(registry, team)},
                              ensure_ascii=False)
        except (teams_store.TeamsStoreError, ValueError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] team-group create failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class TeamGroupDetailHandler:
    """``GET/PUT/DELETE /api/team-groups/{team_id}``."""

    def GET(self, team_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            team = teams_store.get_team(team_id)
            from agent.registry import get_agent_registry
            return json.dumps(
                {"status": "success", "team": _team_view(get_agent_registry(), team)},
                ensure_ascii=False)
        except KeyError:
            return json.dumps({"status": "error", "message": "team not found"})
        except Exception as e:
            logger.error(f"[WebChannel] team-group read failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def PUT(self, team_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            team = teams_store.update_team(
                team_id,
                name=body.get("name"),
                leader=body.get("leader"),
                members=body.get("members"),
            )
            from agent.registry import get_agent_registry
            return json.dumps(
                {"status": "success", "team": _team_view(get_agent_registry(), team)},
                ensure_ascii=False)
        except KeyError:
            return json.dumps({"status": "error", "message": "team not found"})
        except (teams_store.TeamsStoreError, ValueError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] team-group update failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def DELETE(self, team_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            teams_store.delete_team(team_id)
            return json.dumps({"status": "success"})
        except KeyError:
            return json.dumps({"status": "error", "message": "team not found"})
        except Exception as e:
            logger.error(f"[WebChannel] team-group delete failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})