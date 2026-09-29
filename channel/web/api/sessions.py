"""The session endpoints: /api/sessions, /api/history and the per-session
settings the composer chips write to.

Everything about a conversation that is not the act of sending a message:
listing and renaming sessions, replaying history, the permission mode and
model chosen for one session, clearing and compacting its context.

The step-rendering helpers at the top are here because replaying history is
the only thing that reads stored steps back: a live turn streams them as
they happen.
"""

from typing import Dict, List, Optional
import json

import web

from agent.permission import (
    MODES as PERMISSION_MODES,
    global_mode as permission_global_mode,
    normalize_mode as permission_normalize_mode,
)
from channel.web.api.models import ModelsHandler
from channel.web.core._common import (
    _agent_badge,
    _build_artifact_payload,
    _get_workspace_root,
    _request_agent_id,
    _require_auth,
    _rewrite_relative_media,
    _roster_from_members,
)
from channel.web.core.channel import WebChannel
from channel.web.core.providers import PROVIDER_MODELS
from common import const
from common.log import logger
from config import conf
from models import model_catalog


def _paths_written_by_step(step: dict) -> list:
    """Files a persisted tool step produced, if any.

    `write`/`edit` name theirs in the arguments. A `subagent` step lists the
    ones its sub agents wrote in its result: those files never passed through
    a tool call of this agent's own, so nothing else records them.
    """
    name = step.get("name")
    if name in ("write", "edit"):
        args = step.get("arguments")
        path = str((args or {}).get("path") or "").strip() if isinstance(args, dict) else ""
        return [path] if path else []
    if name != "subagent":
        return []
    try:
        results = json.loads(step.get("result") or "{}").get("results") or []
    except (ValueError, TypeError, AttributeError):
        return []
    return [
        path
        for item in results if isinstance(item, dict)
        for path in (item.get("files") or [])
    ]


def _artifacts_from_steps(steps, session_id: str = None, agent_id: str = None) -> list:
    """
    Rebuild the artifact cards of a persisted assistant message.

    History replay has no SSE events, so the tool calls are the only record.
    Doing this server-side keeps one implementation of the workspace-internal
    filter — and lets absolute paths inside the workspace be recognised, which
    a client mirroring the rules can't do.

    ``session_id`` anchors detection to the session's working dir (the project
    dir when one is open), matching the live SSE path; otherwise state_root.
    """
    from agent.protocol.artifact import get_workspace_root, safe_build_artifact

    out = []
    seen = set()
    root = None
    for step in steps or []:
        if not isinstance(step, dict) or step.get("type") != "tool" or step.get("is_error"):
            continue
        for path in _paths_written_by_step(step):
            if root is None:
                root = _get_workspace_root(session_id, agent_id) if session_id else get_workspace_root()
            info = safe_build_artifact(path, root)
            if not info or info["path"] in seen:
                continue
            seen.add(info["path"])
            payload = _build_artifact_payload(info)
            if payload:
                out.append(payload)
    return out


def _add_subagent_displays(steps) -> None:
    """Give persisted `subagent` steps the same readable form they had live.

    `display` is deliberately kept out of the model's context, so it is not in
    the stored conversation either. Rebuilding it here means a reloaded page
    shows the sub agents' reports rather than the JSON the model was handed.
    """
    from agent.tools.subagent import format_results

    for step in steps or []:
        if not isinstance(step, dict) or step.get("name") != "subagent":
            continue
        try:
            results = json.loads(step.get("result") or "{}").get("results")
        except (ValueError, TypeError, AttributeError):
            continue
        if isinstance(results, list) and results:
            step["display"] = format_results(results)


def _add_delegate_displays(steps) -> None:
    """Give persisted `agent_delegate` steps the readable form they had live.

    Same story as `_add_subagent_displays`: `display` is kept out of the model's
    context and so out of storage, so a reloaded page would otherwise show the
    JSON handed to the model rather than "who → whom" and the teammate's reply.
    """
    from agent.tools.agent_delegate.agent_delegate import format_delegate_result

    for step in steps or []:
        if not isinstance(step, dict) or step.get("name") != "agent_delegate":
            continue
        try:
            payload = json.loads(step.get("result") or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or not payload.get("content"):
            continue
        source_id = payload.get("delegated_by") or ""
        source_name = source_id
        try:
            from bridge.bridge import Bridge

            source_name = (
                Bridge().get_agent_bridge().agent_registry.get(source_id).name
                or source_id
            )
        except Exception:
            pass
        step["display"] = format_delegate_result(
            source_name,
            payload.get("agent_name") or payload.get("agent_id") or "",
            payload.get("content") or "",
            status=payload.get("status") or "done",
        )


def _generate_session_title(user_message: str, assistant_reply: str = "",
                            session_id: str = "") -> str:
    """Delegate to the shared SessionService implementation."""
    from agent.chat.session_service import generate_session_title
    return generate_session_title(user_message, assistant_reply, session_id)


def _annotate_sessions_with_projects(store, result: dict, agent_id: Optional[str]) -> None:
    """Attach each session's project space, and say how to group the list.

    ``group_mode`` is decided here rather than in the browser because the client
    only ever holds one page: whether more than one space is in play is a fact
    about all sessions, not about the fifty currently on screen.

    - ``time``    one space in use (the common case) - group by 今天/昨天/更早,
                  exactly as before projects existed.
    - ``project`` several spaces in use - group by project, so multi-project
                  users can find a conversation by where it belongs.
    """
    from agent.workspace import project_store
    from common.state_dir import state_root_str

    project_map = project_store.get_project_map(agent_id)
    default_workspace = state_root_str()

    for session in result.get("sessions") or []:
        path = project_map.get(session["session_id"])
        session["project"] = (
            {"path": path, "name": project_store.display_name_for(path)}
            if path else None
        )

    # Distinct spaces across every web session, default workspace included as
    # one space when any session is still using it.
    space_paths = set()
    uses_default = False
    for sid in store.list_session_ids(channel_type="web"):
        path = project_map.get(sid)
        if path:
            space_paths.add(path)
        else:
            uses_default = True

    result["space_count"] = len(space_paths) + (1 if uses_default else 0)
    result["group_mode"] = "project" if result["space_count"] > 1 else "time"
    result["default_workspace"] = default_workspace
    # The user's chosen sidebar order of spaces (project paths + the default
    # sentinel). The client uses it to sort project groups; unspecified spaces
    # fall back after the ordered ones.
    result["project_order"] = project_store.get_order()


def _as_epoch(value) -> int:
    """Best-effort convert a session timestamp into a sortable epoch int.

    New databases store ``last_active``/``created_at`` as integer Unix
    timestamps, but a workspace carried over from an older build may still hold
    them as ``'YYYY-MM-DD HH:MM:SS'`` strings. Parsing those defensively keeps
    the merged session list from crashing the whole API (which would leave the
    web sidebar empty) just because one legacy row can't be ``int()``-ed.
    """
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    from datetime import datetime

    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except ValueError:
            continue
    return 0


def _list_sessions_across_agents(page: int, page_size: int) -> dict:
    """One page of every Agent's conversations, merged.

    Sessions are stored one database per Agent, so "all conversations" is a
    merge across files rather than a query. Each Agent is asked for as many rows
    as the requested page could possibly draw from it, because any of them can
    supply the row that sorts into that page.

    Presenting them in one list is what keeps a second Agent from feeling like a
    second account: the alternative, switching the whole console to look at
    another Agent's conversations, makes the roster a tenant selector.
    """
    from agent.memory import get_conversation_store
    from agent.registry import get_agent_registry
    from agent.workspace import project_store, session_prefs
    from common.state_dir import state_root_str

    take = max(1, page) * page_size
    merged: List[dict] = []
    total = 0
    space_paths = set()
    uses_default = False
    try:
        members_index = session_prefs.members_index()
    except Exception as e:
        # Faces are decoration; losing them must not cost the user the list.
        logger.warning(f"[WebChannel] Could not read session rosters: {e}")
        members_index = {}

    for profile in get_agent_registry().list(include_disabled=False):
        try:
            store = get_conversation_store(profile.workspace)
            chunk = store.list_sessions(channel_type="web", page=1, page_size=take)
            project_map = project_store.get_project_map(profile.id)
            session_ids = store.list_session_ids(channel_type="web")
        except Exception as e:
            # One unreadable workspace must not blank out the whole list; the
            # other Agents' conversations are still perfectly readable.
            logger.warning(
                f"[WebChannel] Skipping sessions for agent={profile.id}: {e}"
            )
            continue

        total += chunk.get("total", 0)
        badge = _agent_badge(profile)
        for session in chunk.get("sessions") or []:
            path = project_map.get(session["session_id"])
            session["agent"] = badge
            # Only a conversation with more than one Agent in it needs faces in
            # the list; a solo one reads better as a plain row, exactly as it
            # did before there was a roster.
            roster = _roster_from_members(
                profile.id, members_index.get((profile.id, session["session_id"]))
            )
            if len(roster) > 1:
                session["participants"] = roster
            session["project"] = (
                {"path": path, "name": project_store.display_name_for(path)}
                if path else None
            )
            merged.append(session)

        for sid in session_ids:
            path = project_map.get(sid)
            if path:
                space_paths.add(path)
            else:
                uses_default = True

    # One row per conversation. A session id can exist in more than one Agent's
    # store (an older client once let a conversation change hands mid-way, and
    # each side kept the turns it saw); showing it twice makes both rows light
    # up as "selected". Keep the copy holding the bulk of the conversation —
    # that's the one the user recognises — and let the newest break a tie.
    by_id: Dict[str, dict] = {}
    for session in merged:
        sid = session.get("session_id")
        kept = by_id.get(sid)
        if kept is None or (
            (int(session.get("msg_count") or 0), _as_epoch(session.get("last_active")))
            > (int(kept.get("msg_count") or 0), _as_epoch(kept.get("last_active")))
        ):
            by_id[sid] = session
    total -= len(merged) - len(by_id)
    merged = list(by_id.values())

    # Same ordering the per-Agent query applies, so a merged page looks exactly
    # like a single Agent's page does.
    merged.sort(
        key=lambda s: (
            0 if s.get("pinned") else 1,
            -_as_epoch(s.get("last_active")),
        )
    )
    offset = (max(1, page) - 1) * page_size
    result = {
        "sessions": merged[offset:offset + page_size],
        "total": total,
        "page": max(1, page),
        "page_size": page_size,
        "has_more": total > offset + page_size,
        "space_count": len(space_paths) + (1 if uses_default else 0),
        "default_workspace": state_root_str(),
        "project_order": project_store.get_order(),
    }
    result["group_mode"] = "project" if result["space_count"] > 1 else "time"
    return result


class SessionsHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(
                page='1', page_size='50', agent_id='', agent='', scope=''
            )
            page = int(params.page)
            page_size = int(params.page_size)
            if (params.scope or '').strip() == 'all':
                result = _list_sessions_across_agents(page, page_size)
                return json.dumps({"status": "success", **result}, ensure_ascii=False)

            agent_id = _request_agent_id(params)
            from agent.memory import get_conversation_store
            from agent.registry import get_agent_registry
            store = get_conversation_store(
                _get_workspace_root(agent_id=agent_id)
            )
            result = store.list_sessions(
                channel_type="web",
                page=page,
                page_size=page_size,
            )
            _annotate_sessions_with_projects(store, result, agent_id)
            badge = _agent_badge(
                get_agent_registry().get(agent_id or None, require_enabled=False)
            )
            for session in result.get("sessions") or []:
                session["agent"] = badge
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Sessions API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionDetailHandler:
    def DELETE(self, session_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        logger.info(f"[WebChannel] DELETE session request: {session_id}")
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})
            params = web.input(agent_id='')
            agent_id = _request_agent_id(params)

            # Stop any in-flight run first: a reply that lands after the delete
            # would otherwise keep burning tokens for a session nobody can see.
            try:
                from agent.protocol import get_cancel_registry
                from bridge.bridge import Bridge
                scoped = Bridge().get_agent_bridge().scoped_session_key(session_id)
                cancelled = get_cancel_registry().cancel_session(scoped)
                if cancelled:
                    logger.info(
                        f"[WebChannel] Cancelled {cancelled} in-flight request(s) "
                        f"for deleted session {session_id}"
                    )
            except Exception as e:
                logger.warning(f"[WebChannel] Cancel on delete failed: {e}")

            from agent.memory import get_conversation_store
            store = get_conversation_store(_get_workspace_root(agent_id=agent_id))
            store.clear_session(session_id)

            # Drop the session's side stores too. Left behind, a stale project
            # binding would keep inflating the "how many spaces are in use"
            # count that decides how the session list is grouped.
            try:
                from agent.workspace import project_store, session_prefs
                project_store.forget_session(session_id)
                session_prefs.forget_session(session_id)
            except Exception as e:
                logger.debug(f"[WebChannel] Session side-store cleanup skipped: {e}")

            # Also remove the Agent instance from AgentBridge if exists
            try:
                from bridge.bridge import Bridge
                ab = Bridge().get_agent_bridge()
                ab.clear_session(session_id, agent_id=agent_id)
            except Exception:
                pass

            channel = WebChannel()
            # Drop messages still waiting in the channel queue: processing them
            # after the delete would recreate the session from scratch.
            try:
                channel.cancel_session(session_id)
            except Exception as e:
                logger.warning(f"[WebChannel] Failed to drain queue on delete: {e}")
            channel.session_queues.pop(
                channel._session_queue_key(session_id, agent_id), None
            )

            logger.info(f"[WebChannel] Session deleted: {session_id}")
            return json.dumps({"status": "success"})
        except Exception as e:
            logger.error(f"[WebChannel] Session delete error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def PUT(self, session_id: str):
        """Update a session's title and/or its pinned flag."""
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})
            body = json.loads(web.data())
            agent_id = _request_agent_id(body)
            title = (body.get("title") or "").strip()
            pinned = body.get("pinned")
            if not title and pinned is None:
                return json.dumps({"status": "error", "message": "title or pinned required"})

            from agent.memory import get_conversation_store
            store = get_conversation_store(_get_workspace_root(agent_id=agent_id))

            found = True
            if title:
                found = store.rename_session(session_id, title)
            if pinned is not None:
                found = store.set_pinned(session_id, bool(pinned)) and found
            if not found:
                # A session only gets a row once its first message is stored, so
                # this is also what a pin on a brand-new empty chat looks like.
                return json.dumps({"status": "error", "message": "session not found"})
            return json.dumps({"status": "success"})
        except Exception as e:
            logger.error(f"[WebChannel] Session update error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


def _session_model_catalog() -> List[dict]:
    """Providers a session may switch to, newest-first within each provider.

    Only providers with a credential on file are offered: listing one without an
    API key would let the user pick a model that fails on the next message.
    The globally active provider is always included, even if its key lives in
    the environment rather than in config.json.
    """
    local_config = conf()
    active_bot_type = local_config.get("bot_type") or ""
    active_provider = "openai" if active_bot_type == const.CHATGPT else active_bot_type
    if local_config.get("use_linkai") and local_config.get("linkai_api_key"):
        active_provider = "linkai"
    active_model = str(local_config.get("model") or "").strip()
    catalog_map = model_catalog.get_catalog_map()
    hidden_map = model_catalog.get_hidden_map()

    catalog: List[dict] = []
    for pid, pinfo in PROVIDER_MODELS.items():
        if pid == "custom" or not pinfo.get("models"):
            continue
        key_field = pinfo.get("api_key_field")
        has_key = bool(key_field and str(local_config.get(key_field) or "").strip())
        if not has_key and pid != active_provider:
            continue
        # Overlay onto the presets, then keep only text-tagged entries — only
        # those belong in the conversation switcher. Without an overlay this is
        # just the preset model list.
        if catalog_map.get(pid) or hidden_map.get(pid):
            effective = ModelsHandler._merged_catalog(
                pid, ModelsHandler._preset_seed(pid), catalog_map, hidden_map)
            models = [e["name"] for e in effective if "text" in (e.get("capabilities") or [])]
        else:
            models = list(pinfo["models"])
        if not models:
            continue
        # The user can pin a custom model name to a built-in provider (via the
        # global config / capability "custom model" field). That model won't be
        # in the preset list, so surface it here for the active provider so the
        # chat picker can both display and re-select it.
        if pid == active_provider and active_model and active_model not in models:
            models.insert(0, active_model)
        catalog.append({
            "id": pid,
            "label": pinfo["label"],
            "models": models,
        })

    # User-defined OpenAI-compatible providers carry their own credentials, so
    # offer any that have a key on file (or are the active provider). Their model
    # list combines the provider's configured default with the globally active
    # model when this custom provider is the one in use — otherwise a custom
    # provider added without a preset model would be unselectable in chat.
    try:
        from models.custom_provider import get_custom_providers
        for cp in get_custom_providers():
            cid = cp.get("id")
            if not cid:
                continue
            pid = f"custom:{cid}"
            is_active = pid == active_provider
            # Mirror the config page's "configured" test (_custom_provider_cards):
            # a keyless-but-based endpoint (self-hosted / gateway) is valid, so
            # having an api_base counts just like having a key.
            configured = bool(str(cp.get("api_base") or "").strip()) \
                or bool(str(cp.get("api_key") or "").strip())
            if not configured and not is_active:
                continue
            entries = catalog_map.get(pid)
            if entries:
                models = [e["name"] for e in entries if "text" in (e.get("capabilities") or [])]
            else:
                models = []
                cp_model = str(cp.get("model") or "").strip()
                if cp_model:
                    models.append(cp_model)
            if is_active and active_model and active_model not in models:
                models.insert(0, active_model)
            if not models:
                # Nothing concrete to select yet (no default model and not the
                # active provider) — skip rather than render an empty group.
                continue
            name = cp.get("name") or cid
            catalog.append({
                "id": pid,
                "label": {"zh": name, "en": name},
                "models": models,
            })
    except Exception as e:
        logger.debug(f"[WebChannel] custom providers unavailable: {e}")

    return catalog


def _session_settings_state(session_id: str, agent_id: Optional[str]) -> dict:
    """Effective model + permission for a session, and what it can be changed to.

    ``source`` tells the UI whether a value is this conversation's own choice or
    inherited, so it can show "follow global" as a real, selectable state instead
    of silently duplicating the global value onto every session.

    The model resolves the same way the runtime does (see AgentLLMModel.model):
    the conversation's pin, else the owning Agent's own default model, else the
    global config. ``source`` is ``session`` / ``agent`` / ``global`` accordingly,
    and ``agent`` carries the Agent's default when it has one, so a fresh chat
    with a specialist Agent shows the model it will really answer with.
    """
    from agent.workspace import session_prefs

    local_config = conf()
    prefs = session_prefs.get_prefs(session_id, agent_id)

    global_bot_type = local_config.get("bot_type") or ""
    global_provider = "openai" if global_bot_type == const.CHATGPT else global_bot_type
    if local_config.get("use_linkai") and local_config.get("linkai_api_key"):
        global_provider = "linkai"
    global_model = local_config.get("model") or ""
    global_permission = permission_global_mode()

    # The default Agent never has a model of its own: it *is* the global choice.
    agent_default = None
    try:
        from agent.registry import get_agent_registry
        registry = get_agent_registry()
        profile = registry.get(agent_id or None, require_enabled=False)
        if profile.id != registry.default_agent_id and profile.model:
            agent_default = {
                "model": profile.model,
                "provider": profile.bot_type or global_provider,
            }
    except Exception as e:
        logger.debug(f"[WebChannel] agent default model unavailable: {e}")

    if prefs.get("model"):
        effective_model, effective_provider, source = prefs["model"], prefs.get("provider"), "session"
    elif agent_default:
        effective_model, effective_provider, source = agent_default["model"], agent_default["provider"], "agent"
    else:
        effective_model, effective_provider, source = global_model, global_provider, "global"

    return {
        "model": {
            "model": effective_model,
            "provider": effective_provider or global_provider,
            "source": source,
            "global": {"model": global_model, "provider": global_provider},
            "agent": agent_default,
            "providers": _session_model_catalog(),
        },
        "permission": {
            "mode": (
                permission_normalize_mode(prefs["permission"], global_permission)
                if prefs.get("permission") else global_permission
            ),
            "source": "session" if prefs.get("permission") else "global",
            "global": global_permission,
            "modes": list(PERMISSION_MODES),
        },
        "team": _session_team_state(prefs, agent_id),
    }


def _session_team_state(prefs: dict, agent_id: Optional[str]) -> dict:
    """Who else is on this conversation, and who could be added.

    An archived member is reported but marked unavailable rather than dropped,
    so the roster the user set is what the roster page shows.

    Ids are read the way the conversation reads them, reserved "default" alias
    included: a member the chat can already address must not be shown here as
    an unknown, unavailable row, and the agent behind it must not be offered
    again as somebody left to invite.
    """
    from agent.registry import get_agent_registry

    registry = get_agent_registry()
    owner = registry.get_addressed(agent_id, require_enabled=False)
    owner_id = owner.id
    members = []
    seen = set()
    for member_id in prefs.get("members") or []:
        try:
            profile = registry.get_addressed(member_id, require_enabled=False)
        except Exception:
            members.append({"id": member_id, "name": member_id, "available": False})
            continue
        # Keyed on the resolved id: an alias and the id it resolves to are one
        # teammate, so the panel lists the row once like the roster does.
        if profile.id in seen:
            continue
        seen.add(profile.id)
        members.append({
            **_agent_badge(profile),
            "available": profile.enabled and profile.id != owner_id,
        })
    return {
        "owner": _agent_badge(owner),
        "members": members,
        "candidates": [
            _agent_badge(profile)
            for profile in registry.list(include_disabled=False)
            if profile.id != owner_id
        ],
    }


class SessionSettingsHandler:
    """Per-session model and permission overrides.

    Both are stored outside the sessions table (see session_prefs) so they can be
    set before the conversation has its first message, and both fall back to the
    global config when unset.
    """

    def GET(self, session_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})
            params = web.input(agent='', agent_id='')
            state = _session_settings_state(
                session_id, params.agent or params.agent_id or None
            )
            return json.dumps({"status": "success", **state}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Session settings read error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self, session_id: str):
        """Set or clear this session's model / permission.

        Send ``null`` for a field to drop the override and follow the global
        setting again. ``model`` and ``provider`` move together: a model without
        its provider would be routed by the global bot type.
        """
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            from agent.workspace import session_prefs
            body = json.loads(web.data() or b"{}")
            agent_id = body.get("agent") or body.get("agent_id")

            updates = {}
            if "permission" in body:
                mode = body.get("permission")
                updates["permission"] = (
                    permission_normalize_mode(mode) if mode else None
                )
            if "model" in body or "provider" in body:
                model = (body.get("model") or "").strip() or None
                provider = (body.get("provider") or "").strip() or None
                # Clearing the model clears its provider too: a pinned provider
                # with no model would route the global model to the wrong vendor.
                updates["model"] = model
                updates["provider"] = provider if model else None
            if "members" in body:
                raw = body.get("members")
                if raw is None:
                    updates["members"] = None
                elif isinstance(raw, list):
                    updates["members"] = [
                        str(item).strip() for item in raw if str(item).strip()
                    ]
                else:
                    return json.dumps({
                        "status": "error",
                        "message": "members must be a list of agent ids",
                    })

            if not updates:
                return json.dumps({
                    "status": "error",
                    "message": "permission, model, provider or members required",
                })

            session_prefs.set_prefs(session_id, agent_id, **updates)

            # Retarget the live agent so the change lands on the next message
            # without waiting for a fresh get_agent.
            try:
                from bridge.bridge import Bridge
                ab = Bridge().get_agent_bridge()
                agent = ab.get_cached_agent(session_id, agent_id)
                if agent is not None:
                    ab.apply_session_prefs(agent, session_id, agent_id)
            except Exception as e:
                logger.debug(f"[WebChannel] session prefs apply-to-agent skipped: {e}")

            logger.info(
                f"[WebChannel] Session settings updated: sid={session_id}, {updates}"
            )
            state = _session_settings_state(session_id, agent_id)
            return json.dumps({"status": "success", **state}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Session settings update error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionTitleHandler:
    def POST(self, session_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            body = json.loads(web.data())
            agent_id = _request_agent_id(body)
            user_message = body.get("user_message", "")
            assistant_reply = body.get("assistant_reply", "")
            if not user_message:
                return json.dumps({"status": "error", "message": "user_message required"})

            title = _generate_session_title(user_message, assistant_reply, session_id)

            from agent.memory import get_conversation_store
            store = get_conversation_store(_get_workspace_root(agent_id=agent_id))
            updated = store.rename_session(session_id, title)
            logger.info(f"[WebChannel] Session title set: sid={session_id}, title='{title}', db_updated={updated}")

            return json.dumps({"status": "success", "title": title}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Title generation error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class PromptOptimizeHandler:
    """Optimize a colloquial user prompt into a structured AI-ready instruction."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data() or b"{}")
            user_input = (body.get("input") or "").strip()
            if not user_input:
                return json.dumps({"status": "error", "message": "input required"})

            context_messages = body.get("context_messages", None)

            from agent.chat.session_service import optimize_prompt
            optimized = optimize_prompt(user_input, context_messages)

            return json.dumps(
                {"status": "success", "optimized": optimized},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error(f"[WebChannel] Prompt optimization error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionClearContextHandler:
    def POST(self, session_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})
            params = web.input(agent_id='')
            raw_body = web.data()
            body = json.loads(raw_body) if raw_body else {}
            agent_id = _request_agent_id(body) or _request_agent_id(params)

            # The service clears every participant of a team conversation.
            from agent.chat.session_service import SessionService

            new_seq = SessionService().clear_context(session_id, agent_id=agent_id)
            return json.dumps({"status": "success", "context_start_seq": new_seq})
        except Exception as e:
            logger.error(f"[WebChannel] Clear context error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionContextUsageHandler:
    def GET(self, session_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            # Live agent instances are keyed by (agent_id, session_id), so a
            # non-default agent's context is only found when its id is supplied.
            # Without this the lookup falls back to the default agent and always
            # reports available=false for e.g. content-writer sessions.
            from urllib.parse import parse_qs
            agent_id = _request_agent_id(parse_qs(web.ctx.env.get("QUERY_STRING") or ""))

            from bridge.bridge import Bridge
            bridge = Bridge()
            ab = bridge.get_agent_bridge()
            # peek_agent, not get_agent: the latter builds the agent on miss
            # (MCP + skills), and this endpoint is called on hover.
            agent = ab.peek_agent(session_id, agent_id=agent_id)
            if agent is None:
                # No live context yet — a fresh session, or one just cleared
                # (clear_context drops the instance).
                return json.dumps({"status": "success", "available": False})

            usage = agent.get_context_usage()
            usage["status"] = "success"
            return json.dumps(usage)
        except Exception as e:
            logger.error(f"[WebChannel] Context usage error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionCompactContextHandler:
    """Synchronous manual compaction (same logic as the /compact command).

    Runs compact_context() on the live agent and returns the refreshed usage so
    the frontend can redraw the pie without a separate fetch. peek_agent (not
    get_agent) so an empty session is a no-op instead of building an agent.
    """

    def POST(self, session_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            # Match the agent that owns this session (instances are keyed by
            # (agent_id, session_id)); otherwise compaction targets the wrong
            # agent and no-ops for non-default agents.
            params = web.input(agent_id='')
            raw_body = web.data()
            body = json.loads(raw_body) if raw_body else {}
            agent_id = _request_agent_id(body) or _request_agent_id(params)

            from bridge.bridge import Bridge
            bridge = Bridge()
            ab = bridge.get_agent_bridge()
            agent = ab.peek_agent(session_id, agent_id=agent_id)
            if agent is None:
                # No live context — nothing to compact.
                return json.dumps({
                    "status": "success", "ok": False, "available": False,
                    "compacted_turns": 0, "before": 0, "after": 0, "usage": None,
                })

            result = agent.compact_context()
            usage = None
            try:
                usage = agent.get_context_usage()
            except Exception:
                pass

            return json.dumps({
                "status": "success",
                "ok": bool(result.get("ok")),
                "compacted_turns": result.get("compacted_turns", 0),
                "before": result.get("before", 0),
                "after": result.get("after", 0),
                "usage": usage,
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Compact context error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class HistoryHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        web.header('Access-Control-Allow-Origin', '*')
        try:
            params = web.input(session_id='', page='1', page_size='20', agent_id='', until_seq='')
            session_id = params.session_id.strip()
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            agent_id = _request_agent_id(params)
            from agent.memory import get_conversation_store
            store = get_conversation_store(
                _get_workspace_root(agent_id=agent_id)
            )
            until_seq = params.until_seq.strip()
            page = int(params.page)
            # A reply still streaming is shown as of its last stored point and
            # followed live from there, so nothing appears twice or goes missing.
            live = None
            if page == 1 and not until_seq:
                try:
                    live = WebChannel().resumable_stream(session_id, agent_id)
                except Exception as e:
                    logger.debug(f"[WebChannel] resumable stream lookup skipped: {e}")
            result = store.load_history_page(
                session_id=session_id,
                page=page,
                page_size=int(params.page_size),
                until_seq=int(until_seq) if until_seq.lstrip('-').isdigit() else None,
                max_seq=live["stored_seq"] if live else None,
            )
            if live:
                messages = result.get("messages") or []
                last = messages[-1] if messages else {}
                running = last.get("role") == "assistant" and last.get("run_state") == "running"
                # Before the run starts there is nothing stored to line up
                # with; once it has, only its own unfinished turn is followed.
                if running or live["stored_seq"] is None:
                    result["active_request"] = {
                        "request_id": live["request_id"],
                        "after_seq": live["after_seq"],
                    }
            # Same workspace-relative media rewrite the live SSE path applies,
            # so images/videos survive a page reload for non-default agents.
            history_root = None
            try:
                history_root = _get_workspace_root(session_id, agent_id)
            except Exception as e:
                logger.debug(f"[WebChannel] history workspace root skipped: {e}")
            for msg in result.get("messages") or []:
                if msg.get("role") != "assistant":
                    continue
                if history_root and isinstance(msg.get("content"), str):
                    try:
                        msg["content"] = _rewrite_relative_media(
                            msg["content"], history_root
                        )
                    except Exception as e:
                        logger.debug(f"[WebChannel] history media rewrite skipped: {e}")
                _add_subagent_displays(msg.get("steps"))
                _add_delegate_displays(msg.get("steps"))
                artifacts = _artifacts_from_steps(msg.get("steps"), session_id)
                if artifacts:
                    msg["artifacts"] = artifacts
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] History API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class UserMessagesHandler:
    """Lightweight index of a session's user messages for the nav timeline.

    Returns only ``{seq, preview, created_at}`` per user turn, so the whole
    conversation's user-message list can be fetched at once regardless of how
    many messages there are; the main history stays paginated.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        web.header('Access-Control-Allow-Origin', '*')
        try:
            params = web.input(session_id='', agent_id='')
            session_id = params.session_id.strip()
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            agent_id = _request_agent_id(params)
            from agent.memory import get_conversation_store
            store = get_conversation_store(
                _get_workspace_root(agent_id=agent_id)
            )
            result = store.list_user_messages(session_id=session_id)
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] User messages API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class MessageDeleteHandler:
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        web.header('Access-Control-Allow-Origin', '*')
        try:
            data = json.loads(web.data())
            agent_id = _request_agent_id(data)
            session_id = data.get('session_id', '').strip()
            user_seq = data.get('user_seq')
            delete_user = data.get('delete_user', True)
            cascade = data.get('cascade', False)
            
            if not session_id or user_seq is None:
                return json.dumps({"status": "error", "message": "session_id and user_seq required"})
            
            # 1. Delete from database
            from agent.memory import get_conversation_store
            store = get_conversation_store(_get_workspace_root(agent_id=agent_id))
            deleted = store.delete_message_pair(session_id, int(user_seq), delete_user=delete_user, cascade=cascade)

            # 2. Sync agent's in-memory context so its next turn sees the
            # same history as the DB. Handled by the agent_bridge helper.
            try:
                from bridge.bridge import Bridge
                Bridge().get_agent_bridge().sync_session_messages_from_store(
                    session_id, agent_id=agent_id
                )
            except Exception as sync_err:
                logger.warning(f"[WebChannel] Failed to sync agent memory: {sync_err}")

            return json.dumps({"status": "success", "deleted": deleted}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Message delete error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
