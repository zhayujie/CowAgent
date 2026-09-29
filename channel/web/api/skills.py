"""The skills view's endpoints: /api/tools and /api/skills.

The built-in tools the Agent can call, the skills installed alongside them,
the viewer that reads a skill's files, and the two ways a new skill arrives:
written from a form, or uploaded and previewed before it is installed.
"""

import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from typing import List, Optional

import web

from channel.web.core._common import (
    _ensure_list,
    _get_workspace_root,
    _raw_web_input,
    _read_uploaded_file_bytes_limited,
    _request_agent_id,
    _require_auth,
    _scoped_agent_id,
)
from common.log import logger


class ToolsHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.tool_manager import ToolManager
            from common import i18n
            tm = ToolManager()
            if not tm.tool_classes:
                tm.load_tools()
            tools = []
            lang = i18n.get_language()
            for name, cls in tm.tool_classes.items():
                try:
                    instance = cls()
                    desc = instance.description
                    if lang == i18n.ZH_HANT and desc:
                        desc = i18n.to_traditional(desc)
                    elif lang == "en" and name == "scheduler":
                        desc = (
                            "Create, query and manage scheduled tasks (reminders, periodic tasks, etc.).\n\n"
                            "⚠️ IMPORTANT: Only use this tool when delayed or periodic execution is needed."
                        )
                    tools.append({
                        "name": name,
                        "description": desc,
                    })
                except Exception:
                    tools.append({"name": name, "description": ""})
            return json.dumps({"status": "success", "tools": tools}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Tools API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


def _install_skill_for_agent(spec: str, agent_id: str = None):
    """Install a skill into the selected Agent's skills directory."""
    from cli.commands.skill import install_skill

    return install_skill(spec, agent_id=agent_id)


_LOCAL_PATH_PREFIXES = ("./", "../", "/", "~", "\\")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
_GITHUB_SHORTHAND_RE = re.compile(r"^[A-Za-z0-9_\-]+/[A-Za-z0-9_.\-]+(?:#.+)?$")


def _market_spec(source: str, value: str) -> str:
    """Turn the console's (source, value) pair into an installer spec.

    Explicit per source so that, say, ``owner/repo`` typed into the Skill Hub
    box cannot silently turn into a GitHub install, and so the console can
    never reach the installer's local-path route.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("value is required")
    if value.startswith(_LOCAL_PATH_PREFIXES):
        raise ValueError("local paths cannot be installed from the console")
    if source == "hub":
        if not _SKILL_NAME_RE.match(value):
            raise ValueError(f"invalid skill name: {value}")
        return value
    if source == "clawhub":
        if value.startswith("clawhub:"):
            value = value[len("clawhub:"):]
        if not _SKILL_NAME_RE.match(value):
            raise ValueError(f"invalid ClawHub skill name: {value}")
        return f"clawhub:{value}"
    if source == "github":
        if value.startswith(("https://", "http://")) or _GITHUB_SHORTHAND_RE.match(value):
            return value
        raise ValueError("expected a GitHub URL or owner/repo")
    raise ValueError(f"unknown source: {source}")


class _SkillStaging:
    """Skills fetched for preview, held until confirmed, discarded, or stale."""

    TTL_SECONDS = 30 * 60
    DIR_PREFIX = "cow-skill-preview-"

    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}

    def create(self, agent_id):
        self._sweep()
        token = uuid.uuid4().hex
        path = tempfile.mkdtemp(prefix=self.DIR_PREFIX)
        with self._lock:
            self._items[token] = {"dir": path, "agent_id": agent_id, "created": time.time()}
        return token, path

    def get(self, token):
        self._sweep()
        with self._lock:
            return self._items.get(token or "")

    def discard(self, token):
        with self._lock:
            item = self._items.pop(token or "", None)
        if item:
            shutil.rmtree(item["dir"], ignore_errors=True)

    def _sweep(self):
        cutoff = time.time() - self.TTL_SECONDS
        with self._lock:
            stale = [t for t, item in self._items.items() if item["created"] < cutoff]
            tracked = {item["dir"] for item in self._items.values()}
        for token in stale:
            self.discard(token)
        # Previews left behind by a restart are no longer tracked; drop them once stale.
        root = tempfile.gettempdir()
        try:
            names = os.listdir(root)
        except OSError:
            return
        for name in names:
            path = os.path.join(root, name)
            if not name.startswith(self.DIR_PREFIX) or path in tracked:
                continue
            try:
                if os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue


_staging = _SkillStaging()


def _preview_response(token, path, result, agent_id):
    """Answer a staging attempt: the skills found, or why there are none."""
    from cli.commands.skill import describe_staged

    if result.error:
        _staging.discard(token)
        return json.dumps({"status": "error", "message": result.error}, ensure_ascii=False)
    skills = describe_staged(path, agent_id=agent_id)
    if not skills:
        _staging.discard(token)
        return json.dumps({"status": "error", "message": "no skills found"}, ensure_ascii=False)
    return json.dumps({
        "status": "success",
        "token": token,
        "skills": skills,
        "messages": result.messages,
    }, ensure_ascii=False)


def _mcp_workspace(source=None) -> str:
    agent_id = _request_agent_id(source) if source is not None else None
    return _get_workspace_root(agent_id=agent_id)


def _skill_service(agent_id: str = ''):
    """
    A SkillService over the skills the console manages.

    Skills stay anchored to the agent's state root even while a session has a
    project open, so this deliberately resolves the workspace without a session.
    ``agent_id`` selects which agent's skills to manage, so a multi-agent setup
    keeps each agent's library isolated.
    """
    from agent.skills.manager import SkillManager
    from agent.skills.service import SkillService
    from common import state_dir
    workspace_root = _get_workspace_root(agent_id=agent_id or None)
    custom_dir = str(state_dir.skills_dir(base=workspace_root))
    return SkillService(SkillManager(custom_dir=custom_dir))


class McpServersHandler:
    """List and persist MCP servers from the Agent's mcp.json."""

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.mcp.service import list_servers_with_status

            params = web.input(agent_id='')
            result = list_servers_with_status(_mcp_workspace(params))
            return json.dumps({
                "status": "success",
                "hint": "Saved MCP servers apply on the next message; no process restart is required.",
                **result,
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] MCP list error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def PUT(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.mcp.service import (
                McpConfigError,
                list_servers_with_status,
                refresh_mcp_managers,
                save_servers,
            )

            body = json.loads(web.data() or b"{}")
            workspace = _mcp_workspace(body)
            servers = body.get("servers")
            if servers is None:
                return json.dumps({"status": "error", "message": "servers is required"})
            save_servers(workspace, servers)
            refresh_mcp_managers()
            result = list_servers_with_status(workspace)
            return json.dumps({
                "status": "success",
                "hint": "Saved MCP servers apply on the next message; no process restart is required.",
                **result,
            }, ensure_ascii=False)
        except McpConfigError as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] MCP save error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class McpServerTestHandler:
    """Dry-run one MCP server config without writing mcp.json."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.mcp.service import McpConfigError, probe_server

            body = json.loads(web.data() or b"{}")
            cfg = body.get("server") if isinstance(body.get("server"), dict) else body
            result = probe_server(cfg or {})
            status = "success" if result.get("ok") else "error"
            return json.dumps({"status": status, **result}, ensure_ascii=False)
        except McpConfigError as e:
            return json.dumps({
                "status": "error",
                "ok": False,
                "error": str(e),
                "tools": [],
                "needs_auth": False,
                "message": str(e),
            })
        except Exception as e:
            logger.error(f"[WebChannel] MCP test error: {e}")
            return json.dumps({
                "status": "error",
                "ok": False,
                "error": str(e),
                "tools": [],
                "message": str(e),
            })


class SkillsHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from common import i18n
            params = web.input(agent_id='')
            # The library page lists everything installed, unnarrowed by the
            # Agent's selection: a skill it has not selected still has to be
            # visible here for the selection to be editable at all.
            service = _skill_service(_request_agent_id(params))
            skills = service.query()
            if i18n.get_language() == i18n.ZH_HANT:
                for skill in skills:
                    if isinstance(skill, dict):
                        for k, v in list(skill.items()):
                            if k in ("name", "description", "display_name") and isinstance(v, str):
                                skill[k] = i18n.to_traditional(v)
            return json.dumps({"status": "success", "skills": skills}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Skills API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data() or b"{}")
            action = (body.get("action") or "").strip()
            name = (body.get("name") or "").strip()
            if not action:
                return json.dumps({"status": "error", "message": "action is required"})
            agent_id = _request_agent_id(body)
            service = _skill_service(agent_id)
            if action == "open":
                if not name:
                    return json.dumps({"status": "error", "message": "action and name are required"})
                service.open({"name": name})
            elif action == "close":
                if not name:
                    return json.dumps({"status": "error", "message": "action and name are required"})
                service.close({"name": name})
            elif action == "delete":
                if not name:
                    return json.dumps({"status": "error", "message": "action and name are required"})
                info = next((item for item in service.query() if item.get("name") == name), None)
                if info and not info.get("deletable", True):
                    return json.dumps({
                        "status": "error",
                        "message": "built-in skills cannot be deleted",
                    })
                service.delete({"name": name})
            elif action == "preview":
                from cli.commands.skill import stage_skill

                try:
                    spec = _market_spec(body.get("source") or "", body.get("value") or "")
                except ValueError as e:
                    return json.dumps({"status": "error", "message": str(e)})
                token, path = _staging.create(agent_id)
                try:
                    result = stage_skill(spec, path)
                except Exception:
                    _staging.discard(token)
                    raise
                return _preview_response(token, path, result, agent_id)
            elif action == "confirm":
                from cli.commands.skill import commit_staged

                staged = _staging.get(body.get("token"))
                if not staged:
                    return json.dumps({"status": "error", "message": "preview expired, fetch it again"})
                names = body.get("names")
                if names is not None and not isinstance(names, list):
                    return json.dumps({"status": "error", "message": "names must be a list"})
                try:
                    installed = commit_staged(staged["dir"], names, agent_id=staged["agent_id"])
                finally:
                    _staging.discard(body.get("token"))
                _skill_service(staged["agent_id"]).manager.refresh_skills()
                logger.info(f"[WebChannel] Skills installed: {installed}")
                return json.dumps({"status": "success", "installed": installed}, ensure_ascii=False)
            elif action == "discard":
                _staging.discard(body.get("token"))
            elif action == "install":
                spec = (body.get("spec") or name).strip()
                if not spec:
                    return json.dumps({"status": "error", "message": "spec is required"})
                if spec.startswith(_LOCAL_PATH_PREFIXES):
                    return json.dumps({"status": "error", "message": "local paths cannot be installed from the console"})
                result = _install_skill_for_agent(spec, agent_id)
                if result.error:
                    return json.dumps({"status": "error", "message": result.error})
                service.manager.refresh_skills()
                return json.dumps({
                    "status": "success",
                    "installed": result.installed,
                    "messages": result.messages,
                }, ensure_ascii=False)
            else:
                return json.dumps({"status": "error", "message": f"unknown action: {action}"})
            return json.dumps({"status": "success"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Skills POST error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


def _oversize_body(limit: int) -> Optional[str]:
    """An error response when the declared body is already over ``limit``.

    Read from the header before the body is, so an oversized upload is refused
    instead of being buffered first. A header that is missing or unreadable
    simply does not trigger this; the per-file caps still apply.
    """
    try:
        length = int(getattr(web.ctx, "env", {}).get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return None
    if length > limit:
        return json.dumps({"status": "error", "message": "upload too large"})
    return None


def _uploaded_files(params, max_bytes: int) -> List[dict]:
    """The files a multipart request carries, each with the path it keeps.

    A folder pick sends its files under ``files`` and their paths - relative to
    the folder itself - under ``relative_paths``, the pairing the chat upload
    already uses. A plain multi-file pick sends no paths, so each file keeps its
    own name.
    """
    uploaded = _ensure_list(params.get("files"))
    rel_paths = _ensure_list(params.get("relative_paths"))
    if rel_paths and len(rel_paths) != len(uploaded):
        raise ValueError("upload payload mismatch: a path per file is required")

    items = []
    for index, file_obj in enumerate(uploaded):
        # NOTE: cgi.FieldStorage raises TypeError on a truthy check, so an
        # uploaded file is always compared against None.
        if file_obj is None:
            continue
        path = rel_paths[index] if rel_paths else getattr(file_obj, "filename", "")
        # A form submitted with the file input left empty still sends the field,
        # as a part with no file name. There is nothing to write for it.
        if not path:
            continue
        items.append({
            "path": path,
            "content": _read_uploaded_file_bytes_limited(file_obj, max_bytes),
        })
    return items


class SkillCreateHandler:
    """
    ``POST /api/skills/create`` - a skill written from the console's form.

    Multipart rather than JSON, because the form collects a name, a description
    and the instructions *and* any number of files to bundle beside them.
    """

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.skills.service import SkillService

            oversize = _oversize_body(SkillService.MAX_UPLOAD_TOTAL_SIZE)
            if oversize:
                return oversize

            params = _raw_web_input()
            service = _skill_service(_scoped_agent_id(params))
            result = service.create({
                "name": params.get("name", ""),
                "description": params.get("description", ""),
                "body": params.get("body", ""),
                "files": _uploaded_files(params, SkillService.MAX_UPLOAD_FILE_SIZE),
            })
            logger.info(f"[WebChannel] Skill created: {result['name']} "
                        f"({len(result['files'])} bundled file(s))")
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except ValueError as e:
            # What the user typed or picked, refused: the name, the missing
            # description, a file too large. Reported as itself, not as a 500.
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Skill create error: {e}", exc_info=True)
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def _multipart_lists(max_parts: int) -> dict:
    """
    The request's multipart form, every field as a list of all its values.

    Newer web.py parses forms with the ``multipart`` package, keeps only the
    last value of a repeated field, and inherits that package's 128-part cap.
    A folder upload repeats ``files`` and ``paths`` once per file, so the body
    is parsed here directly whenever that package is what web.py relies on.
    """
    multipart = getattr(getattr(web, "webapi", None), "multipart", None)
    env = web.ctx.env
    content_type = (env.get("CONTENT_TYPE") or "").lower()
    if not hasattr(multipart, "parse_form_data") or not content_type.startswith("multipart/"):
        return {key: _ensure_list(value) for key, value in _raw_web_input().items()}
    forms, files = multipart.parse_form_data(
        environ=env, ignore_errors=False, part_limit=max_parts,
    )
    return {
        key: forms.getall(key) + files.getall(key)
        for key in set(forms.keys()) | set(files.keys())
    }


class SkillUploadHandler:
    """Stage an uploaded skill (archive, SKILL.md, or folder) for preview."""

    MAX_TOTAL_BYTES = 50 * 1024 * 1024
    MAX_FILES = 2000

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from cli.commands.skill import stage_skill_upload

            content_length = int(getattr(web.ctx, "env", {}).get("CONTENT_LENGTH") or 0)
            if content_length > self.MAX_TOTAL_BYTES:
                return json.dumps({"status": "error", "message": "upload too large (max 50 MB)"})
            params = _multipart_lists(self.MAX_FILES * 2 + 16)
            agent_id = _scoped_agent_id(params)
            uploaded = params.get("files") or []
            # Folder uploads carry each file's path inside the folder in a
            # parallel field: multipart filenames lose directory components.
            paths = params.get("paths") or []
            if not uploaded:
                return json.dumps({"status": "error", "message": "no files uploaded"})
            if len(uploaded) > self.MAX_FILES:
                return json.dumps({"status": "error", "message": f"too many files (max {self.MAX_FILES})"})

            files, total = [], 0
            for index, file_obj in enumerate(uploaded):
                if file_obj is None:
                    continue
                rel = paths[index] if index < len(paths) and isinstance(paths[index], str) else ""
                rel = rel or getattr(file_obj, "filename", "") or ""
                content = _read_uploaded_file_bytes_limited(file_obj, self.MAX_TOTAL_BYTES)
                total += len(content)
                if total > self.MAX_TOTAL_BYTES:
                    return json.dumps({"status": "error", "message": "upload too large (max 50 MB)"})
                files.append((rel, content))

            token, path = _staging.create(agent_id)
            try:
                result = stage_skill_upload(files, path)
            except Exception:
                _staging.discard(token)
                raise
            return _preview_response(token, path, result, agent_id)
        except Exception as e:
            logger.error(f"[WebChannel] Skill upload error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SkillFilesHandler:
    """
    ``GET /api/skills/files`` - the files one skill is made of.

    A skill is a directory: the console needs the tree to show anything beyond
    its SKILL.md, since the files beside it - ``scripts/``, ``references/``,
    bundled assets - are installed by an upload but named nowhere in the skill
    list.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(name='', agent_id='')
            name = (params.name or '').strip()
            if not name:
                return json.dumps({"status": "error", "message": "name is required"})
            result = _skill_service(_request_agent_id(params)).list_files(name)
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Skill files error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SkillContentHandler:
    """
    One file of a skill, for the console's viewer and editor.

    The skill is addressed by name rather than by path, because the loader is
    what resolves a name to a directory: a workspace skill shadows a builtin of
    the same name, and a builtin sits outside the workspace that the file APIs
    are confined to. ``path`` then names a file inside that directory, and
    defaults to the skill's SKILL.md.

    Unlike the skill list, the text is served exactly as stored - no
    simplified-to-traditional conversion. What comes back here is what a save
    would write, and rewriting someone's file into another script because of
    the console's display language is not a conversion they asked for.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(name='', path='', agent_id='')
            name = (params.name or '').strip()
            if not name:
                return json.dumps({"status": "error", "message": "name is required"})
            result = _skill_service(_request_agent_id(params)).read_content(
                name, path=(params.path or '').strip() or None,
            )
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[WebChannel] Skill content error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.workspace.service import WorkspaceConflictError

            body = json.loads(web.data() or b'{}')
            name = (body.get("name") or "").strip()
            if not name:
                return json.dumps({"status": "error", "message": "name is required"})
            content = body.get("content")
            if not isinstance(content, str):
                return json.dumps({"status": "error", "message": "content must be a string"})

            try:
                result = _skill_service(_request_agent_id(body)).write_content(
                    name, content, expected_mtime=body.get("expected_mtime"),
                    path=(body.get("path") or "").strip() or None,
                )
            except WorkspaceConflictError as e:
                return json.dumps({"status": "error", "code": "conflict", "message": str(e)})

            logger.info(f"[WebChannel] Skill saved: {name}/{result['path']} "
                        f"({result['size']} bytes)")
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except PermissionError:
            return json.dumps({"status": "error", "message": "permission denied"})
        except Exception as e:
            logger.error(f"[WebChannel] Skill write error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
