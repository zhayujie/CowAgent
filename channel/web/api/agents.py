"""The agents view's endpoints: /api/agents and friends.

The Agent roster -- create, edit, delete -- their core files and their
avatars. Editing an Agent has to reach past the config file: the running
services hold a snapshot of the roster, so _reload_agent_runtime rebuilds
what changed, and _bind_channel_instance re-points the IM channels an Agent
answers on.
"""

from typing import Optional
import json
import os

import web

from channel.web.core._common import (
    _live_channel_manager,
    _raw_web_input,
    _read_uploaded_file_bytes,
    _require_auth,
)
from common.log import logger
from config import conf, get_data_root


def _agent_admin_service():
    from agent.admin import AgentAdminService
    return AgentAdminService(os.path.join(get_data_root(), "config.json"))


def _bind_channel_instance(channel_type: str, instance_id: str = "", agent_id: str = "", members=None):
    """Point one channel instance at an Agent (and team), hot-swapping without a restart.

    The binding lives on the channel instance itself (channel_instances[].agent_id
    in team.json), the single source of truth for routing. For a single-instance
    channel the instance id is just the channel type. An empty agent_id unbinds it
    (falls back to the default Agent).

    Rebinding only changes *which* Agent inbound messages route to — the
    credentials, connection, and scheduled tasks are untouched. Tasks live in
    the global store and carry their own ``agent_id``; flipping this picker
    must never migrate or rewrite them. We persist the new binding and then set
    ``bound_agent_id`` live on the running channel; the next inbound message
    reads the updated value. This avoids the reconnect storm a restart caused
    when the user flipped the picker a few times.
    """
    from channel.channel_instances import upsert_instance

    ctype = (channel_type or "").strip().lower()
    if not ctype:
        raise ValueError("channel_type is required")
    target_id = (instance_id or "").strip() or ctype
    agent_id = (agent_id or "").strip()

    inst = upsert_instance(
        conf(),
        channel_type=ctype,
        instance_id=target_id,
        agent_id=agent_id,
        members=members,
    )

    try:
        mgr = _live_channel_manager()
        channel = mgr.get_channel(target_id) if mgr else None
        if channel is not None:
            # Live-update owner + team on the running instance. Empty owner means
            # "follow the default Agent". No restart: this only changes routing.
            channel.bound_agent_id = agent_id
            channel.members = list(inst.members or [])
            # Kept in step with the record so a rebind does not leave the running
            # instance pointing at a stale way of reaching its teammates.
            channel.peers = [dict(p) for p in (inst.peers or [])]
            logger.info(
                f"[WebChannel] Channel '{target_id}' rebound to "
                f"'{agent_id or 'default'}' with team {inst.members or []} (no restart)"
            )
    except Exception as e:
        logger.error(
            f"[WebChannel] Failed to hot-rebind channel '{target_id}': {e}",
            exc_info=True,
        )

    return {
        "instance_id": inst.instance_id,
        "agent_id": inst.agent_id,
        "members": list(inst.members or []),
    }


def _reload_agent_runtime(service, changed_agent_ids=None) -> None:
    """Re-point the live runtime at a freshly loaded roster.

    This runs inside the roster-edit request, so it must stay cheap. The old
    implementation tore everything down - stop every scheduler, drop every
    cached session, then rebuild all of them - which grew linearly with the
    number of Agents (each rebuild reloads dozens of skills). Editing one
    Agent's name should not cost a full-fleet reload.

    Instead we reconcile incrementally:
      * swap the registry/router (always cheap),
      * start a scheduler only for Agents that gained one, stop those that
        disappeared, and leave already-running ones untouched,
      * evict only the sessions of the Agents that actually changed, so their
        next turn picks up the new name / model / persona. Everyone else keeps
        their warm cache.

    ``changed_agent_ids`` narrows the session eviction to just the edited
    Agents. When omitted we fall back to evicting nothing extra beyond the
    add/remove diff, since pure metadata edits without an id (e.g. binding
    changes) touch no cached runtime.
    """
    from agent.registry import set_agent_registry
    from agent.routing import AgentRouter, set_agent_router

    settings = service._load()
    registry = service._registry(settings)
    router = AgentRouter.from_config(settings, registry)
    set_agent_registry(registry)
    set_agent_router(router)

    from bridge.bridge import Bridge
    bridge = Bridge()
    agent_bridge = getattr(bridge, "_agent_bridge", None)
    if agent_bridge is None:
        return

    agent_bridge.agent_registry = registry
    agent_bridge.agent_router = router

    # Reconcile schedulers against what is already running, rather than
    # stopping and recreating the whole set.
    from agent.tools.scheduler.integration import init_scheduler, stop_scheduler
    live_ids = {p.id for p in registry.list(include_disabled=False)}
    previously = set(agent_bridge.scheduler_agent_ids)

    for agent_id in previously - live_ids:
        try:
            stop_scheduler(agent_id)
        except Exception as e:
            logger.warning(f"[WebChannel] stop_scheduler({agent_id}) failed: {e}")
        agent_bridge.scheduler_agent_ids.discard(agent_id)

    for profile in registry.list(include_disabled=False):
        if profile.id in previously:
            continue  # already has a running scheduler; init_scheduler is a no-op
        if init_scheduler(agent_bridge, profile.workspace, profile.id):
            agent_bridge.scheduler_agent_ids.add(profile.id)
    agent_bridge.scheduler_initialized = bool(agent_bridge.scheduler_agent_ids)

    # Drop cached runtimes only for the Agents whose definition changed, so the
    # edit takes effect on their next turn without wiping everyone's session.
    for agent_id in (changed_agent_ids or []):
        try:
            agent_bridge.clear_agent(agent_id)
        except Exception as e:
            logger.warning(f"[WebChannel] clear_agent({agent_id}) failed: {e}")


class AgentsHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            return json.dumps(
                {"status": "success", **_annotate_avatar_revs(_agent_admin_service().snapshot())},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error(f"[WebChannel] Agents API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            action = body.get("action")
            service = _agent_admin_service()
            revision = body.get("revision") or None
            if action == "create":
                result = service.create_agent(
                    agent_id=body.get("id", ""),
                    name=body.get("name", ""),
                    # Blank means "put it where a new one goes", which is what
                    # the console sends: it asks for a name, not a path.
                    workspace=body.get("workspace") or None,
                    clone_from=body.get("clone_from") or None,
                    avatar=body.get("avatar") or None,
                    description=body.get("description") or None,
                    skills=body.get("skills"),
                    knowledge=body.get("knowledge"),
                    knowledge_mode=body.get("knowledge_mode") or None,
                    revision=revision,
                )
            elif action == "update":
                updates = {
                    "name": body.get("name"),
                    "enabled": body.get("enabled"),
                    "make_default": bool(body.get("make_default", False)),
                    "avatar": body.get("avatar"),
                    "description": body.get("description"),
                    "model": body.get("model"),
                    "bot_type": body.get("bot_type"),
                    "revision": revision,
                }
                if "skills" in body:
                    updates["skills"] = body.get("skills")
                if "knowledge" in body:
                    updates["knowledge"] = body.get("knowledge")
                result = service.update_agent(body.get("id", ""), **updates)
            elif action == "archive":
                result = service.archive_agent(body.get("id", ""), revision=revision)
            elif action == "delete":
                result = service.delete_agent(body.get("id", ""), revision=revision)
            elif action == "set_knowledge_mode":
                # A filesystem toggle (symlink vs own dir), not a roster edit, so
                # it doesn't participate in the roster revision guard.
                result = service.set_knowledge_mode(
                    body.get("id", ""), body.get("mode", "")
                )
            elif action == "bind_channel_instance":
                # members: list => set team; omitted/None => leave team untouched
                raw_members = body.get("members", None)
                members = raw_members if isinstance(raw_members, list) else None
                result = _bind_channel_instance(
                    channel_type=body.get("channel_type", ""),
                    instance_id=body.get("instance_id", ""),
                    agent_id=body.get("agent_id", ""),
                    members=members,
                )
            else:
                return json.dumps({
                    "status": "error", "message": f"unknown action: {action}"
                })
            # Only the edited Agent needs its cached runtime dropped; a create
            # has no live sessions yet. bind_channel_instance hot-updates the
            # running channel's binding in place (see _bind_channel_instance),
            # so it neither restarts a channel nor touches the roster runtime.
            if action == "bind_channel_instance":
                return json.dumps(
                    {"status": "success", "result": result},
                    ensure_ascii=False,
                )
            changed = None
            if action in ("update", "archive", "delete", "set_knowledge_mode"):
                changed = [body.get("id", "")] if body.get("id") else None
            _reload_agent_runtime(service, changed_agent_ids=changed)
            # Hand back the fresh revision so a client making rapid successive
            # edits (e.g. ticking skill checkboxes) can chain them without a
            # full reload and without tripping the stale-roster guard.
            try:
                revision_after = service.snapshot().get("revision")
            except Exception:
                revision_after = None
            return json.dumps(
                {"status": "success", "result": result, "revision": revision_after},
                ensure_ascii=False,
            )
        except Exception as e:
            from agent.admin import StaleRosterError
            code = None
            if isinstance(e, StaleRosterError):
                web.ctx.status = "409 Conflict"
                code = "stale_roster"
            logger.error(f"[WebChannel] Agents POST error: {e}")
            return json.dumps({"status": "error", "message": str(e), "code": code})


class AgentCoreFileHandler:
    def GET(self, agent_id: str, filename: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            result = _agent_admin_service().read_core_file(agent_id, filename)
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def PUT(self, agent_id: str, filename: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            result = _agent_admin_service().write_core_file(
                agent_id,
                filename,
                body.get("content"),
                body.get("revision", ""),
            )
            try:
                from bridge.bridge import Bridge
                agent_bridge = getattr(Bridge(), "_agent_bridge", None)
                if agent_bridge is not None:
                    agent_bridge.clear_agent(agent_id)
            except Exception as e:
                logger.warning(
                    f"[WebChannel] Failed to evict edited agent={agent_id}: {e}"
                )
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            from agent.admin import StaleAgentFileError
            if isinstance(e, StaleAgentFileError):
                web.ctx.status = "409 Conflict"
            return json.dumps({"status": "error", "message": str(e)})


# An emoji costs nothing to store or serve, so it is the default way to tell
# Agents apart; an uploaded picture sets the field to this token instead and the
# bytes live beside the other shared assets.
AVATAR_IMAGE_TOKEN = "image"
AVATAR_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _avatar_path(agent_id: str) -> Optional[str]:
    from common.state_dir import shared_root

    base = shared_root() / "avatars"
    for suffix in AVATAR_TYPES:
        candidate = base / f"{agent_id}{suffix}"
        if candidate.is_file():
            return str(candidate)
    return None


def _avatar_rev(agent_id: str) -> Optional[str]:
    """A cache-busting token derived from the avatar file's mtime.

    The roster revision only hashes team.json, but replacing an avatar rewrites
    an image file without touching any field there, so the revision stays put
    and the browser keeps serving the cached picture. Keying the URL on the
    file's mtime instead means every upload changes the token and the <img>
    refetches, even after a hard reload where in-memory hints are gone.
    """
    path = _avatar_path(agent_id)
    if not path:
        return None
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return None


def _annotate_avatar_revs(snapshot: dict) -> dict:
    """Attach ``avatar_rev`` to every Agent that carries an uploaded image."""
    for agent in snapshot.get("agents") or []:
        if agent.get("avatar") == AVATAR_IMAGE_TOKEN:
            rev = _avatar_rev(agent.get("id", ""))
            if rev:
                agent["avatar_rev"] = rev
    return snapshot


class AgentAvatarHandler:
    def GET(self, agent_id: str):
        _require_auth()
        path = _avatar_path(agent_id)
        if not path:
            web.ctx.status = "404 Not Found"
            web.header('Content-Type', 'application/json; charset=utf-8')
            return json.dumps({"status": "error", "message": "no avatar"})
        with open(path, "rb") as handle:
            data = handle.read()
        web.header('Content-Type', AVATAR_TYPES[os.path.splitext(path)[1].lower()])
        # Content-addressed by the caller via ?v=, so it can be cached hard.
        web.header('Cache-Control', 'private, max-age=86400')
        return data

    def POST(self, agent_id: str):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from common.state_dir import shared_root
            from agent.registry import get_agent_registry

            get_agent_registry().get(agent_id, require_enabled=False)
            # Read the multipart body raw. web.input() decodes it as UTF-8, which
            # dies on the first non-text byte of an image (a PNG starts with the
            # byte 0x89) with "utf-8 codec can't decode byte 0x89". rawinput hands
            # back the bytes untouched, the same path the knowledge upload uses.
            params = _raw_web_input()
            upload = params.get("avatar")
            if upload is None:
                return json.dumps({"status": "error", "message": "avatar file required"})
            filename = getattr(upload, "filename", "") or ""
            raw = _read_uploaded_file_bytes(upload)
            if not raw:
                return json.dumps({"status": "error", "message": "avatar file required"})
            if len(raw) > MAX_AVATAR_BYTES:
                return json.dumps({"status": "error", "message": "avatar exceeds 2 MiB"})
            suffix = os.path.splitext(filename)[1].lower()
            if suffix not in AVATAR_TYPES:
                return json.dumps({
                    "status": "error",
                    "message": f"unsupported image type: {suffix or 'unknown'}",
                })

            base = shared_root() / "avatars"
            base.mkdir(parents=True, exist_ok=True)
            # Drop any other extension first, so one Agent never ends up with
            # two avatar files and a resolution order deciding which one wins.
            for other in AVATAR_TYPES:
                stale = base / f"{agent_id}{other}"
                if other != suffix and stale.is_file():
                    try:
                        stale.unlink()
                    except OSError:
                        pass
            target = base / f"{agent_id}{suffix}"
            tmp = base / f".{agent_id}{suffix}.tmp"
            with open(tmp, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)

            service = _agent_admin_service()
            result = service.update_agent(agent_id, avatar=AVATAR_IMAGE_TOKEN)
            # An avatar is a file plus a metadata flag; it changes nothing about
            # routing, sessions or schedulers. Skipping the full runtime reload
            # keeps the upload instant instead of tearing everything down.
            # Hand back the fresh revision so the console can patch its roster in
            # place without a full reload and without going stale on the next edit.
            revision = service.snapshot().get("revision")
            return json.dumps(
                {"status": "success", "result": result, "revision": revision},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error(f"[WebChannel] Agent avatar upload error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
