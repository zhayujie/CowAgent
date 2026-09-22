"""The skills view's endpoints: /api/tools and /api/skills.

The built-in tools the Agent can call, the skills installed alongside them,
the viewer that reads a skill's definition file, and the two ways a new skill
arrives: written from a form, or uploaded as a folder or an archive.
"""

import json
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
            body = json.loads(web.data())
            action = body.get("action")
            name = body.get("name")
            if not action or not name:
                return json.dumps({"status": "error", "message": "action and name are required"})
            service = _skill_service(_request_agent_id(body))
            if action == "open":
                service.open({"name": name})
            elif action == "close":
                service.close({"name": name})
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


class SkillUploadHandler:
    """
    ``POST /api/skills/upload`` - skills installed from a folder or an archive.

    One upload can hold several skills - a folder of them, an archive of a repo -
    so the response reports every skill separately: installed, replaced, or
    skipped with the reason, rather than one status for the batch.
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

            archive = params.get("archive")
            if archive is not None and getattr(archive, "filename", ""):
                payload = {"archive": {
                    "filename": archive.filename,
                    # Capped at the whole-upload limit rather than the per-file
                    # one: an archive is one file holding the entire skill.
                    "content": _read_uploaded_file_bytes_limited(
                        archive, SkillService.MAX_UPLOAD_TOTAL_SIZE),
                }}
            else:
                payload = {"files": _uploaded_files(params, SkillService.MAX_UPLOAD_FILE_SIZE)}

            result = service.install_upload(payload)
            logger.info(f"[WebChannel] Skills uploaded: installed={result['installed']} "
                        f"replaced={result['replaced']} skipped={len(result['skipped'])}")
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except ValueError as e:
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Skill upload error: {e}", exc_info=True)
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


class SkillContentHandler:
    """
    A skill's definition file, for the console's viewer and editor.

    Addressed by skill name rather than by path, because the loader is what
    resolves a name to a file: a workspace skill shadows a builtin of the same
    name, and a builtin sits outside the workspace that the file APIs are
    confined to.

    Unlike the skill list, the text is served exactly as stored - no
    simplified-to-traditional conversion. What comes back here is what a save
    would write, and rewriting someone's file into another script because of
    the console's display language is not a conversion they asked for.
    """

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(name='', agent_id='')
            name = (params.name or '').strip()
            if not name:
                return json.dumps({"status": "error", "message": "name is required"})
            result = _skill_service(_request_agent_id(params)).read_content(name)
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
                )
            except WorkspaceConflictError as e:
                return json.dumps({"status": "error", "code": "conflict", "message": str(e)})

            logger.info(f"[WebChannel] Skill saved: {name} ({result['size']} bytes)")
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except (ValueError, FileNotFoundError) as e:
            return json.dumps({"status": "error", "message": str(e)})
        except PermissionError:
            return json.dumps({"status": "error", "message": "permission denied"})
        except Exception as e:
            logger.error(f"[WebChannel] Skill write error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
