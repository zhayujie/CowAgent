"""The skills view's endpoints: /api/tools and /api/skills.

The built-in tools the Agent can call, the skills installed alongside them,
and the viewer that reads a skill's definition file.
"""

import json

import web

from channel.web.core._common import (
    _get_workspace_root,
    _request_agent_id,
    _require_auth,
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
            elif action == "install":
                spec = (body.get("spec") or name).strip()
                if not spec:
                    return json.dumps({"status": "error", "message": "spec is required"})
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
