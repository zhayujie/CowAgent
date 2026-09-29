"""The workspace panel's endpoints: /api/workspace/* and /api/projects/*.

Browsing, reading and writing files in the Agent's workspace or in an opened
project, and managing the project list itself. Memory and knowledge files
live under the workspace but are owned by the system rather than a project,
which is what _is_system_asset_rel and _system_workspace_service sort out.
"""

from urllib.parse import quote
import json
import os
import sys

import web

from channel.web.core._common import (
    _build_preview_url,
    _is_path_allowed,
    _get_workspace_root,
    _require_auth,
)
from common.log import logger


def _workspace_service(session_id: str = None, agent_id: str = None):
    from agent.workspace.service import WorkspaceService
    return WorkspaceService(_get_workspace_root(session_id, agent_id))


# one of these resolves against the project and misses; we fall back to the
# system directory so preview/@ still work.
_SYSTEM_ASSET_PREFIXES = ("memory/", "memory\\", "knowledge/", "knowledge\\")
_SYSTEM_ASSET_FILES = ("MEMORY.md", "AGENT.md", "USER.md", "RULE.md")


def _is_system_asset_rel(rel_path: str) -> bool:
    """True if a relative path points at a state_root-anchored system asset."""
    p = (rel_path or "").lstrip("./")
    return p in _SYSTEM_ASSET_FILES or p.startswith(_SYSTEM_ASSET_PREFIXES)


def _system_workspace_service():
    from agent.workspace.service import WorkspaceService
    from common.state_dir import state_root_str
    return WorkspaceService(state_root_str())


def _decorate_entry(svc, entry: dict) -> dict:
    """Attach the URLs the frontend needs to preview or download an entry."""
    if entry.get("is_dir"):
        return entry
    abs_path = entry.get("abs_path") or os.path.join(svc.root, entry["path"])
    entry["abs_path"] = abs_path
    entry["raw_url"] = f"/api/file?path={quote(abs_path)}"
    entry["preview_url"] = _build_preview_url(abs_path)
    return entry


class WorkspaceTreeHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(path='', show_hidden='', session='', agent='')
            svc = _workspace_service(params.session or None, params.agent or None)
            result = svc.list_dir(params.path, show_hidden=params.show_hidden == '1')
            result["entries"] = [_decorate_entry(svc, e) for e in result["entries"]]
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Workspace tree error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class WorkspaceSearchHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(q='', limit='30', session='', agent='')
            try:
                limit = max(1, min(100, int(params.limit)))
            except (TypeError, ValueError):
                limit = 30
            svc = _workspace_service(params.session or None, params.agent or None)
            result = svc.search(params.q, limit=limit)
            result["results"] = [_decorate_entry(svc, e) for e in result["results"]]
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Workspace search error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class WorkspaceResolveHandler:
    """
    Metadata + preview/raw URLs for one entry, given a relative or absolute path.

    Directories resolve as well (the client then browses instead of previewing),
    just without the file URLs.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.protocol.artifact import classify_kind, is_previewable
            params = web.input(path='', session='', agent='')
            raw_path = (params.path or '').strip()
            if not raw_path:
                return json.dumps({"status": "error", "message": "path is required"})

            svc = _workspace_service(params.session or None, params.agent or None)
            if os.path.isabs(os.path.expanduser(raw_path)):
                abs_path = os.path.realpath(os.path.expanduser(raw_path))
                if not _is_path_allowed(abs_path):
                    return json.dumps({"status": "error", "message": "Path not allowed"})
                is_dir = os.path.isdir(abs_path)
                if not is_dir and not os.path.isfile(abs_path):
                    return json.dumps({"status": "error", "message": "File not found"})
                kind = "directory" if is_dir else classify_kind(abs_path)
                entry = {
                    "name": os.path.basename(abs_path),
                    "path": svc.to_rel(abs_path),
                    "abs_path": abs_path,
                    "is_dir": is_dir,
                    "kind": kind,
                    "previewable": (not is_dir) and is_previewable(kind),
                    "size": 0 if is_dir else os.path.getsize(abs_path),
                    "mtime": os.path.getmtime(abs_path),
                }
            else:
                try:
                    entry = svc.stat_file(raw_path)
                except FileNotFoundError:
                    # Memory/knowledge live in state_root, not the project. Retry
                    # there so their cards still preview when a project is open.
                    if _is_system_asset_rel(raw_path):
                        entry = _system_workspace_service().stat_file(raw_path)
                    else:
                        raise

            # A directory has nothing to serve; the client browses into it.
            if not entry["is_dir"]:
                entry["raw_url"] = f"/api/file?path={quote(entry['abs_path'])}"
                entry["preview_url"] = _build_preview_url(entry["abs_path"])
            return json.dumps({"status": "success", "file": entry}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Workspace resolve error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class WorkspaceMetaHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(session='', agent='')
            svc = _workspace_service(params.session or None, params.agent or None)
            return json.dumps({"status": "success", **svc.meta()}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Workspace meta error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


def _editable_target(raw_path: str, session_id: str = None, agent_id: str = None):
    """
    Locate a file for the preview panel's text editor: (service, rel_path).

    Narrower than `/api/workspace/resolve`, which only has to serve bytes and so
    accepts anything under the configured serve roots. Reading and writing text
    stay inside the session's workspace (its project dir or the default state
    root), with a fallback to the state root for the memory / knowledge / persona
    assets that live there even while a project is open.
    """
    svc = _workspace_service(session_id, agent_id)
    system = _system_workspace_service()
    try:
        rel = svc.to_workspace_rel(raw_path)
    except ValueError:
        # Absolute path outside the session workspace: the state root is the
        # only other place the console is allowed to edit.
        return system, system.to_workspace_rel(raw_path)
    if svc.root != system.root and _is_system_asset_rel(rel) \
            and not os.path.isfile(svc.resolve(rel)):
        return system, rel
    return svc, rel


def _mark_memory_dirty(agent_id: str = None) -> None:
    """Flag the agent's memory index stale after a console edit to a memory file.

    The index is built from the file contents, so a human edit here must be
    re-embedded the same way an agent's write/edit tool triggers it — otherwise
    semantic search keeps returning the pre-edit text until something else marks
    the store dirty. Best-effort: a failure here must not fail the save.
    """
    try:
        from bridge.bridge import Bridge
        agent = Bridge().get_agent_bridge().get_agent(agent_id=agent_id or None)
        mm = getattr(agent, "memory_manager", None)
        if mm:
            mm.mark_dirty()
    except Exception as e:
        logger.warning(f"[WebChannel] Failed to mark memory index dirty: {e}")


class WorkspaceReadHandler:
    """
    Text content of one workspace file, for the preview panel's editor.

    Returns the `mtime` the client passes back on save and an `editable` flag,
    so the editor never opens a file it would be unable to write back.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(path='', session='', agent='')
            raw_path = (params.path or '').strip()
            if not raw_path:
                return json.dumps({"status": "error", "message": "path is required"})
            svc, rel = _editable_target(raw_path, params.session or None, params.agent or None)
            return json.dumps({"status": "success", **svc.read_text(rel)}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Workspace read error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class WorkspaceWriteHandler:
    """
    Save edited text back to a workspace file.

    A human editing a file in the console is not an agent tool call, so the
    session's agent permission mode does not apply here; the guard is the
    workspace boundary enforced by `_editable_target`.

    `expected_mtime` carries the timestamp the editor loaded. When it no longer
    matches, the response is `code: "conflict"` so the client can offer to
    reload or overwrite rather than silently discarding the newer content -
    which the agent may well have written mid-edit.
    """

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.utils.memory_path import indexes_rel_path
            from agent.workspace.service import WorkspaceConflictError

            body = json.loads(web.data() or b'{}')
            raw_path = (body.get("path") or "").strip()
            if not raw_path:
                return json.dumps({"status": "error", "message": "path is required"})
            content = body.get("content")
            if not isinstance(content, str):
                return json.dumps({"status": "error", "message": "content must be a string"})

            agent_id = body.get("agent") or None
            svc, rel = _editable_target(raw_path, body.get("session") or None, agent_id)
            try:
                result = svc.write_text(rel, content, expected_mtime=body.get("expected_mtime"))
            except WorkspaceConflictError as e:
                return json.dumps({"status": "error", "code": "conflict", "message": str(e)})

            # A memory or knowledge file feeds the vector index; re-embed it on
            # edit so search doesn't keep returning the stale pre-edit text.
            # Same check the write/edit tools use, so both paths agree on which
            # files those are.
            if indexes_rel_path(rel):
                _mark_memory_dirty(agent_id)

            logger.info(f"[WebChannel] Workspace file saved: {result['path']} ({result['size']} bytes)")
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except PermissionError:
            return json.dumps({"status": "error", "message": "permission denied"})
        except Exception as e:
            logger.error(f"[WebChannel] Workspace write error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


def _project_state(session_id: str, agent_id: str = None) -> dict:
    """Assemble the project picker state: current selection + recents + root."""
    from agent.workspace import project_store
    from common.state_dir import state_root_str

    current = project_store.get_project_dir(session_id, agent_id) if session_id else None
    # Resolve the default workspace against the Agent this session belongs to,
    # so the selector hint matches the file panel's real root in multi-Agent
    # setups instead of always pointing at the default Agent's workspace.
    from common.runtime_identity import RuntimeIdentity
    default_workspace = state_root_str(RuntimeIdentity(agent_id=agent_id))
    return {
        "current": (
            {"path": current, "name": os.path.basename(current) or current}
            if current else None
        ),
        "default_workspace": default_workspace,
        "projects_root": project_store.projects_root(),
        "recents": project_store.list_recents(),
    }


class ProjectsHandler:
    """List the project picker state for a session (current + recents)."""

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(session='', agent='')
            state = _project_state(params.session or None, params.agent or None)
            return json.dumps({"status": "success", **state}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Projects list error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ProjectSelectHandler:
    """Bind a session to a project directory, or clear it (project_dir=null)."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.workspace import project_store
            body = json.loads(web.data() or b"{}")
            session_id = (body.get("session") or body.get("session_id") or "").strip()
            agent_id = body.get("agent") or body.get("agent_id")
            if not session_id:
                return json.dumps({"status": "error", "message": "session is required"})
            project_dir = body.get("project_dir")
            applied = project_store.set_project_dir(
                session_id, project_dir or None, agent_id
            )
            # Retarget an already-instantiated session agent immediately, so the
            # change takes effect on the next message without a fresh get_agent.
            try:
                from bridge.bridge import Bridge
                ab = Bridge().get_agent_bridge()
                agent = ab.get_cached_agent(session_id, agent_id)
                if agent is not None and getattr(agent, "apply_project_dir", None):
                    agent.apply_project_dir(applied)
            except Exception as e:
                logger.debug(f"[WebChannel] project apply-to-agent skipped: {e}")
            state = _project_state(session_id, agent_id)
            return json.dumps({"status": "success", **state}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Project select error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ProjectCreateHandler:
    """Create a new project folder under the projects root and select it."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.workspace import project_store
            body = json.loads(web.data() or b"{}")
            session_id = (body.get("session") or body.get("session_id") or "").strip()
            agent_id = body.get("agent") or body.get("agent_id")
            name = (body.get("name") or "").strip()
            if not name:
                return json.dumps({"status": "error", "message": "name is required"})
            path = project_store.create_project(name)
            if session_id:
                project_store.set_project_dir(session_id, path, agent_id)
                try:
                    from bridge.bridge import Bridge
                    ab = Bridge().get_agent_bridge()
                    agent = ab.get_cached_agent(session_id, agent_id)
                    if agent is not None and getattr(agent, "apply_project_dir", None):
                        agent.apply_project_dir(path)
                except Exception as e:
                    logger.debug(f"[WebChannel] project apply-to-agent skipped: {e}")
            state = _project_state(session_id or None, agent_id)
            return json.dumps({"status": "success", "path": path, **state}, ensure_ascii=False)
        except (ValueError, FileExistsError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Project create error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ProjectOrderHandler:
    """Persist the user's chosen sidebar order of project spaces."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.workspace import project_store
            body = json.loads(web.data() or b"{}")
            order = body.get("order")
            if not isinstance(order, list):
                return json.dumps({"status": "error", "message": "order must be a list"})
            saved = project_store.set_order(order)
            return json.dumps({"status": "success", "order": saved}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Project order error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ProjectManageHandler:
    """Rename (PUT) or delete (DELETE) a project record.

    Neither touches the folder on disk: a rename only sets a display name, and a
    delete only forgets the CowAgent record and unbinds any sessions (they revert
    to the default workspace). The files stay exactly where they are.
    """

    def PUT(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.workspace import project_store
            body = json.loads(web.data() or b"{}")
            path = (body.get("path") or "").strip()
            if not path:
                return json.dumps({"status": "error", "message": "path is required"})
            name = project_store.rename_project(path, body.get("name") or "")
            return json.dumps({"status": "success", "name": name}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Project rename error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def DELETE(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.workspace import project_store
            body = json.loads(web.data() or b"{}")
            path = (body.get("path") or "").strip()
            agent_id = body.get("agent") or body.get("agent_id")
            if not path:
                return json.dumps({"status": "error", "message": "path is required"})
            unbound = project_store.delete_project(path, agent_id)
            return json.dumps({"status": "success", "unbound": unbound}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Project delete error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


# Virtual path (Windows only) that expands to the list of logical drives, so
# the picker can navigate above a drive root and switch between drives.
_DRIVES_SENTINEL = "__DRIVES__"


class ProjectBrowseHandler:
    """List sub-directories of a path, for the "open project" folder picker.

    Directories only (files are irrelevant when choosing a project root). The
    starting point defaults to the projects root; the parent is included so the
    user can navigate upward.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from common.utils import expand_path
            params = web.input(path='')
            raw = (params.path or '').strip()

            # On Windows, "__DRIVES__" is a virtual path listing all logical
            # drives, so the user can hop across drives from a drive root.
            if sys.platform == 'win32' and raw == _DRIVES_SENTINEL:
                import ctypes

                drives = []
                buf = ctypes.create_unicode_buffer(1024)
                length = ctypes.windll.kernel32.GetLogicalDriveStringsW(1024, buf)
                for drive in buf[:length].split('\x00'):
                    if drive:
                        drives.append({"name": drive.rstrip("\\"), "path": drive})
                return json.dumps({
                    "status": "success",
                    "path": _DRIVES_SENTINEL,
                    "parent": None,
                    "dirs": drives,
                }, ensure_ascii=False)

            # Default entry point is the user's home (~), a familiar anchor for
            # picking a project directory.
            base = os.path.realpath(expand_path(raw)) if raw else os.path.realpath(os.path.expanduser("~"))
            if not os.path.isdir(base):
                base = os.path.realpath(os.path.expanduser("~"))

            dirs = []
            try:
                with os.scandir(base) as it:
                    for entry in it:
                        if entry.name.startswith("."):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                dirs.append({
                                    "name": entry.name,
                                    "path": os.path.join(base, entry.name),
                                })
                        except OSError:
                            continue
            except PermissionError:
                return json.dumps({"status": "error", "message": "permission denied"})

            dirs.sort(key=lambda d: d["name"].lower())
            parent = os.path.dirname(base)

            # On Windows, at a drive root (e.g. C:\) dirname returns the same
            # path, so point parent at the drives list instead of dropping it.
            if sys.platform == 'win32':
                _, tail = os.path.splitdrive(base)
                if tail in (os.sep, os.altsep, ''):
                    parent = _DRIVES_SENTINEL

            return json.dumps({
                "status": "success",
                "path": base,
                "parent": parent if parent != base else None,
                "dirs": dirs,
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Project browse error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
