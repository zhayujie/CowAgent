"""Plugin system: extensions written for the runtime rather than for the model.

A plugin is a directory with a ``plugin.yaml`` and an entry module defining
``apply(ctx)``. Through ``ctx`` it registers tools, slash commands, lifecycle
hooks, skills, MCP servers, channels and model providers; disabling it revokes
all of them at once.

The functions below are the kernel's call sites. Each one is a no-op when no
plugin is enabled and never raises, so a broken plugin cannot break the
module that calls into it.
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Dict, List, Optional

from common.log import logger

from agent.plugin.context import (  # noqa: F401  (re-exported for plugin authors)
    MESSAGE_IN,
    PROMPT_BUILD,
    REPLY_RENDER,
    TOOL_AFTER,
    TURN_END,
    PluginContext,
    PluginError,
)
from agent.plugin.host import COMMAND_TIMEOUT, HookEvent, PluginHost

SECTION_LIMIT = 500

_host: Optional[PluginHost] = None
_host_lock = threading.Lock()


def get_host() -> PluginHost:
    global _host
    if _host is None:
        with _host_lock:
            if _host is None:
                host = PluginHost()
                from agent.plugin.admin import register_admin_command
                register_admin_command(host)
                _host = host
    return _host


def load_plugins():
    """Load enabled plugins at startup. Never raises."""
    try:
        get_host().load_all()
    except Exception as e:
        logger.warning(f"[Plugin] startup failed: {e}")


def _active() -> Optional[PluginHost]:
    host = _host
    return host if host is not None and host.loaded else None


# -- messages and commands ---------------------------------------------------

def _parse_command(text: str):
    text = (text or "").strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split(None, 1)
    if not parts:
        return None
    return parts[0].lower(), (parts[1] if len(parts) > 1 else "")


def dispatch_command(text: str, **info) -> Optional[str]:
    """Answer ``/name args`` if a plugin (or the kernel) registered ``name``."""
    host = _active()
    if host is None:
        return None
    try:
        parsed = _parse_command(text)
        if parsed is None:
            return None
        cmd = host.commands.get(parsed[0])
        if cmd is None:
            return None
        ev = HookEvent("command", text=text, command=cmd.name, args=parsed[1], **info)
        if cmd.plugin_id == "kernel":
            result = cmd.fn(parsed[1], ev)
        else:
            ok, result = host.call(cmd.plugin_id, cmd.fn, parsed[1], ev, timeout=COMMAND_TIMEOUT)
            if not ok:
                return f"[{cmd.plugin_id}] /{cmd.name} failed, see the log for details."
        if result is None:
            return None
        return str(result)
    except Exception as e:
        logger.warning(f"[Plugin] command dispatch failed: {e}")
        return None


def on_message(text: str, **info) -> Dict[str, Any]:
    """Commands first, then ``message.in`` hooks.

    Returns ``{"text": ..., "reply": ...}``: ``reply`` set means answer with
    it and skip the agent; otherwise continue with ``text``.
    """
    out = {"text": text, "reply": None}
    host = _active()
    if host is None:
        return out
    try:
        reply = dispatch_command(text, **info)
        if reply is not None:
            out["reply"] = reply
            return out
        if not host.hooks.get(MESSAGE_IN):
            return out
        fields = {"text": text, "reply": None, **info}
        fields = host.run_hooks(MESSAGE_IN, fields, mutable=("text", "reply"),
                                channel_type=info.get("channel_type"))
        if isinstance(fields.get("text"), str):
            out["text"] = fields["text"]
        if fields.get("reply") is not None:
            out["reply"] = str(fields["reply"])
    except Exception as e:
        logger.warning(f"[Plugin] message.in failed: {e}")
    return out


def render_reply(reply, **info):
    """``reply.render`` hooks: rewrite a reply before it goes out on a channel."""
    host = _active()
    if host is None or not host.hooks.get(REPLY_RENDER) or reply is None:
        return reply
    try:
        fields = host.run_hooks(REPLY_RENDER, {"reply": copy.copy(reply), **info},
                                mutable=("reply",), channel_type=info.get("channel_type"))
        return fields.get("reply") or reply
    except Exception as e:
        logger.warning(f"[Plugin] reply.render failed: {e}")
        return reply


# -- agent loop ----------------------------------------------------------------

def prompt_sections(**info) -> List[str]:
    """``prompt.build`` hooks: short, labeled sections for the system prompt."""
    host = _active()
    if host is None or not host.hooks.get(PROMPT_BUILD):
        return []
    lines: List[str] = []
    try:
        for plugin_id, result in host.collect(PROMPT_BUILD, info):
            title, body = (result if isinstance(result, tuple) and len(result) == 2
                           else (host.records[plugin_id].manifest.title, result))
            body = str(body).strip()
            if not body:
                continue
            if len(body) > SECTION_LIMIT:
                logger.info(f"[Plugin] {plugin_id} prompt section cut to {SECTION_LIMIT} chars")
                body = body[:SECTION_LIMIT]
            lines += [f"## {title} (plugin: {plugin_id})", "", body, ""]
    except Exception as e:
        logger.warning(f"[Plugin] prompt.build failed: {e}")
    return lines


def after_tool(tool_name: str, arguments: dict, result: Any) -> Any:
    """``tool.after`` hooks. A changed result carries a note naming the plugin,
    so the model knows what it reads is not the tool's own output."""
    host = _active()
    if host is None or not host.hooks.get(TOOL_AFTER):
        return result
    try:
        for hook in host.hooks.get(TOOL_AFTER, ()):
            before = result
            fields = host.run_hook(
                hook, {"tool_name": tool_name, "arguments": arguments, "result": result},
                mutable=("result",),
            )
            result = fields.get("result", result)
            if hook.modify and result != before:
                result = f"{result}\n\n[plugin {hook.plugin_id} modified this tool result]"
    except Exception as e:
        logger.warning(f"[Plugin] tool.after failed: {e}")
    return result


def turn_end(**info):
    """``turn.end`` hooks, in the background."""
    host = _active()
    if host is None or not host.hooks.get(TURN_END):
        return
    try:
        from common.runtime_identity import current_identity
        ident = current_identity()
        info.setdefault("session_id", ident.session_id)
        info.setdefault("agent_id", ident.agent_id)
        host.run_hooks(TURN_END, info)
    except Exception as e:
        logger.warning(f"[Plugin] turn.end failed: {e}")


# -- slots -------------------------------------------------------------------

def _plugin_tool(name: str, factory, plugin_id: str):
    tool = factory()
    tool._plugin_id = plugin_id
    return tool


def plugin_tools() -> list:
    """Fresh instances of every plugin tool, for a new Agent session."""
    host = _active()
    if host is None or not host.tools:
        return []
    tools = []
    for name, factory in list(host.tools.items()):
        try:
            tools.append(_plugin_tool(name, factory, host.tool_owner.get(name, "")))
        except Exception as e:
            logger.warning(f"[Plugin] tool {name} could not be created: {e}")
    return tools


def sync_tools_into_agent(agent) -> None:
    """Add tools of newly enabled plugins to a live agent and drop revoked ones."""
    host = _active()
    if host is None or agent is None or not hasattr(agent, "tools"):
        return
    if getattr(agent, "_evolution_restricted", False) or getattr(
        getattr(agent, "agent", None), "_evolution_restricted", False
    ):
        return
    try:
        tools = agent.tools
        if isinstance(tools, dict):
            current = {n for n, t in tools.items() if getattr(t, "_plugin_id", None)}
        elif isinstance(tools, list):
            current = {t.name for t in tools if getattr(t, "_plugin_id", None)}
        else:
            return
        wanted = set(host.tools)
        if current == wanted:
            return
        added = [_plugin_tool(n, host.tools[n], host.tool_owner.get(n, "")) for n in wanted - current]
        removed = current - wanted
        if isinstance(tools, dict):
            for name in removed:
                tools.pop(name, None)
            for tool in added:
                tools.setdefault(tool.name, tool)
        else:
            if removed:
                agent.tools = [t for t in tools if not (getattr(t, "_plugin_id", None) and t.name in removed)]
            names = {t.name for t in agent.tools}
            agent.tools.extend(t for t in added if t.name not in names)
    except Exception as e:
        logger.debug(f"[Plugin] tool sync skipped: {e}")


def tool_writes(tool_name: str) -> Optional[bool]:
    """Whether a plugin tool changes state, for the read-only permission mode.

    None when ``tool_name`` is not a plugin tool. A tool class may say so
    itself with a ``mutating`` attribute; otherwise the plugin's declared
    permissions decide.
    """
    host = _active()
    if host is None:
        return None
    factory = host.tools.get(tool_name)
    if factory is None:
        return None
    flag = getattr(factory, "mutating", None)
    if isinstance(flag, bool):
        return flag
    rec = host.records.get(host.tool_owner.get(tool_name, ""))
    return True if rec is None else rec.manifest.writes


def skill_dirs() -> tuple:
    host = _active()
    return host.skill_dirs if host is not None else ()


def mcp_servers() -> list:
    host = _active()
    return [dict(s) for s in host.mcp_servers] if host is not None else []


def mcp_revision() -> int:
    host = _active()
    return host.mcp_revision if host is not None and host.mcp_servers else 0


def channel_factory(channel_type: str):
    host = _active()
    return host.channels.get(channel_type) if host is not None else None


def provider_factory(bot_type: str):
    host = _active()
    return host.providers.get(bot_type) if host is not None else None
