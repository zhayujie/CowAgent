"""The artifact endpoints: /api/artifacts and its add, pin, rename and delete actions.

The artifact view lists every user-facing file the Agents' conversations
produced, newest first, across Agents. The index itself is written when the
messages that produced the files are stored (see agent/protocol/artifact.py);
these handlers only read it back and decorate each row with what the browser
needs to show and open the file.
"""

import json
import os
from urllib.parse import quote

import web

from channel.web.core._common import _build_preview_url, _require_auth
from common.log import logger
from common.moved_paths import rebase_moved_path

# Filter chips in the view -> the stored kinds they cover.
KIND_GROUPS = {
    "web": ["html"],
    "image": ["image"],
    "media": ["video", "audio"],
    "doc": ["markdown", "pdf", "office", "text", "csv"],
    "other": ["code", "file"],
    # What a menu entry can show as a page of its own; mirrors MENU_KINDS in menu.py.
    "page": ["html", "markdown"],
}


def _display_path(path: str, workspace: str) -> str:
    """Path as the user thinks of it: inside the Agent's workspace, relative to
    it; elsewhere, absolute with the home directory folded to ``~``."""
    try:
        root = os.path.realpath(os.path.expanduser(workspace))
        if os.path.commonpath([path, root]) == root:
            return os.path.relpath(path, root)
    except (ValueError, TypeError):
        pass
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def _payload(row: dict, profile, default_id: str) -> dict:
    from agent.protocol.artifact import is_previewable

    path = rebase_moved_path(row["path"])
    exists = os.path.isfile(path)
    size = row["size"]
    version = 0
    if exists:
        try:
            st = os.stat(path)
            size, version = st.st_size, int(st.st_mtime)
        except OSError:
            exists = False
    kind = row["kind"]
    return {
        "id": row["id"],
        "agent_id": row["agent_id"] or default_id,
        "agent_name": getattr(profile, "name", "") or "",
        "session_id": row["session_id"],
        "session_title": row["session_title"] or "",
        "turn_seq": row["turn_seq"],
        # The console only lists its own conversations, so a file produced in
        # an IM chat (or a session since deleted) can be opened but not traced.
        "can_jump": bool(row["session_exists"]) and row["session_channel"] == "web",
        "abs_path": path,
        "rel_path": _display_path(path, getattr(profile, "workspace", "") or ""),
        "file_name": os.path.basename(path),
        "kind": kind,
        "previewable": exists and is_previewable(kind),
        "size": size,
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "pinned_at": row.get("pinned_at") or 0,
        "title": row.get("title") or "",
        "exists": exists,
        # /api/file is cached by the browser; the mtime keeps a regenerated
        # image from showing its old pixels.
        "raw_url": f"/api/file?path={quote(path)}&v={version}" if exists else "",
        "preview_url": _build_preview_url(path) if exists else "",
    }


class ArtifactsHandler:
    """GET /api/artifacts?scope=all|<agent>&kind=<group>&q=&path=&offset=&limit="""

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(scope="all", kind="", q="", path="", offset="0", limit="60")
            from agent.memory import get_conversation_store
            from agent.registry import get_agent_registry

            registry = get_agent_registry()
            default_id = registry.default_agent_id
            profiles = {p.id: p for p in registry.list(include_disabled=True)}

            # Stored rows name the default Agent "" (see conversation_store).
            def stored_id(agent_id: str) -> str:
                return "" if agent_id == default_id else agent_id

            scope = (params.scope or "all").strip()
            if scope == "all":
                agent_ids = [stored_id(aid) for aid in profiles]
            elif scope in profiles:
                agent_ids = [stored_id(scope)]
            else:
                agent_ids = []

            kind_group = (params.kind or "").strip()
            kinds = KIND_GROUPS.get(kind_group) if kind_group else None

            store = get_conversation_store(registry.get(require_enabled=False).workspace)
            result = store.list_artifacts(
                agent_ids=agent_ids,
                kinds=kinds,
                query=(params.q or "").strip(),
                path=(params.path or "").strip(),
                offset=int(params.offset or 0),
                limit=int(params.limit or 60),
            )
            items = [
                _payload(row, profiles.get(row["agent_id"] or default_id), default_id)
                for row in result["items"]
            ]
            return json.dumps(
                {"status": "success", "items": items, "has_more": result["has_more"]},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error(f"[WebChannel] Artifacts API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ArtifactAddHandler:
    """POST /api/artifacts/add {path, agent_id, session_id, turn_seq}: (re)index
    one file, attributed to the turn it came from when the caller knows it."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            data = json.loads(web.data() or b"{}")
            from agent.memory import get_conversation_store
            from agent.protocol.artifact import classify_kind
            from agent.registry import get_agent_registry

            path = os.path.realpath(os.path.expanduser(str(data.get("path") or "").strip()))
            if not data.get("path") or not os.path.isfile(path):
                return json.dumps({"status": "error", "message": "file not found"})
            session_id = str(data.get("session_id") or "").strip()
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id is required"})
            try:
                turn_seq = int(data["turn_seq"]) if data.get("turn_seq") is not None else None
            except (TypeError, ValueError):
                turn_seq = None

            registry = get_agent_registry()
            profile = registry.get(data.get("agent_id") or None, require_enabled=False)
            store = get_conversation_store(profile.workspace)
            store.record_artifacts(
                session_id,
                [{"path": path, "kind": classify_kind(path),
                  "size": os.path.getsize(path), "source": "manual"}],
                turn_seq=turn_seq,
            )
            rows = store.list_artifacts(path=path, limit=1)["items"]
            item = _payload(rows[0], profile, registry.default_agent_id) if rows else None
            return json.dumps({"status": "success", "item": item}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Artifact add error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ArtifactPinHandler:
    """POST /api/artifacts/pin {id, agent_id, pinned}: keep one entry at the top
    of the timeline, or let it fall back to its place in time."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            data = json.loads(web.data() or b"{}")
            artifact_id = int(data.get("id"))
            from agent.memory import get_conversation_store
            from agent.registry import get_agent_registry

            profile = get_agent_registry().get(data.get("agent_id") or None, require_enabled=False)
            pinned_at = get_conversation_store(profile.workspace).set_artifact_pinned(
                artifact_id, bool(data.get("pinned")),
            )
            if pinned_at is None:
                return json.dumps({"status": "error", "message": "artifact not found"})
            return json.dumps({"status": "success", "pinned_at": pinned_at})
        except Exception as e:
            logger.error(f"[WebChannel] Artifact pin error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


TITLE_MAX = 120


class ArtifactRenameHandler:
    """POST /api/artifacts/rename {id, agent_id, title}: name one entry in the
    view. The file keeps its name on disk; an empty title restores it."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            data = json.loads(web.data() or b"{}")
            artifact_id = int(data.get("id"))
            title = " ".join(str(data.get("title") or "").split())[:TITLE_MAX]
            from agent.memory import get_conversation_store
            from agent.registry import get_agent_registry

            profile = get_agent_registry().get(data.get("agent_id") or None, require_enabled=False)
            if not get_conversation_store(profile.workspace).set_artifact_title(artifact_id, title):
                return json.dumps({"status": "error", "message": "artifact not found"})
            return json.dumps({"status": "success", "title": title}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Artifact rename error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ArtifactDeleteHandler:
    """POST /api/artifacts/delete {id, agent_id}: forget one entry, keep the file."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            data = json.loads(web.data() or b"{}")
            artifact_id = int(data.get("id"))
            from agent.memory import get_conversation_store
            from agent.registry import get_agent_registry

            profile = get_agent_registry().get(data.get("agent_id") or None, require_enabled=False)
            removed = get_conversation_store(profile.workspace).delete_artifact(artifact_id)
            return json.dumps({"status": "success", "removed": removed})
        except Exception as e:
            logger.error(f"[WebChannel] Artifact delete error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
