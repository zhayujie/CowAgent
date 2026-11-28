"""What ``apply(ctx)`` receives.

Every registration a plugin makes goes into its :class:`Scope`. The host only
commits the scope once ``apply`` returns, and revokes it as a whole when the
plugin is disabled, so plugin authors never write cleanup code for anything
registered through ``ctx``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.plugin.manifest import Manifest

# Lifecycle events a hook can attach to.
MESSAGE_IN = "message.in"      # a user message reaches the kernel; may rewrite or answer it
PROMPT_BUILD = "prompt.build"  # the system prompt is assembled; may add a short section
TOOL_AFTER = "tool.after"      # a tool returned; may rewrite the result the model reads
REPLY_RENDER = "reply.render"  # a reply is about to go out on a channel; may rewrite it
TURN_END = "turn.end"          # an agent run finished; observe only

EVENTS = frozenset({MESSAGE_IN, PROMPT_BUILD, TOOL_AFTER, REPLY_RENDER, TURN_END})
MODIFY_EVENTS = frozenset({MESSAGE_IN, TOOL_AFTER, REPLY_RENDER})


class PluginError(Exception):
    pass


@dataclass
class Hook:
    plugin_id: str
    event: str
    fn: Callable
    modify: bool = False
    channel: Optional[str] = None


@dataclass
class Command:
    plugin_id: str
    name: str
    fn: Callable
    help: str = ""


@dataclass
class Scope:
    """Everything one plugin registered."""

    tools: Dict[str, Any] = field(default_factory=dict)
    commands: Dict[str, Command] = field(default_factory=dict)
    hooks: List[Hook] = field(default_factory=list)
    skill_dirs: List[str] = field(default_factory=list)
    mcp_servers: List[dict] = field(default_factory=list)
    channels: Dict[str, Callable] = field(default_factory=dict)
    providers: Dict[str, Callable] = field(default_factory=dict)
    unload: List[Callable] = field(default_factory=list)


class PluginContext:
    """The plugin's handle on the kernel."""

    def __init__(self, manifest: Manifest, plugin_dir: Path, data_dir: Path, config: Dict[str, Any]):
        self.manifest = manifest
        self.id = manifest.id
        self.dir = plugin_dir
        self.config = config
        # A child of the kernel logger, so plugin output lands in the same log.
        self.log = logging.getLogger(f"log.plugin.{manifest.id}")
        self._data_dir = data_dir
        self.scope = Scope()

    @property
    def data_dir(self) -> Path:
        """A directory the plugin owns for its own files; created on first use."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        return self._data_dir

    # -- slots ---------------------------------------------------------

    def tool(self, tool):
        """Register an agent tool: a ``BaseTool`` subclass, instance or factory.

        A class or factory is called once per Agent session, so tools keep
        per-session state the same way built-in tools do.
        """
        from agent.tools.base_tool import BaseTool

        if isinstance(tool, type) and issubclass(tool, BaseTool):
            factory = tool
        elif isinstance(tool, BaseTool):
            factory = lambda t=tool: t
        elif callable(tool):
            factory = tool
        else:
            raise PluginError("ctx.tool() takes a BaseTool subclass, instance or factory")
        probe = factory()
        name = getattr(probe, "name", "")
        if not name:
            raise PluginError("plugin tool has no name")
        self.scope.tools[name] = factory
        return tool

    def command(self, name: str, fn: Optional[Callable] = None, help: str = ""):
        """Register a slash command, ``/name args``. Usable as a decorator.

        The handler gets ``(args, event)`` and returns the reply text, or None
        to let the message continue to the agent.
        """
        name = (name or "").strip().lstrip("/").lower()
        if not name or " " in name:
            raise PluginError(f"invalid command name {name!r}")

        def register(f):
            self.scope.commands[name] = Command(self.id, name, f, help)
            return f

        return register(fn) if fn is not None else register

    def on(self, event: str, fn: Optional[Callable] = None, modify: bool = False, channel: Optional[str] = None):
        """Attach a hook. Usable as a decorator.

        Observe hooks run in the background and cannot change anything.
        Modify hooks run in line with a timeout and need ``hook.modify`` in
        the manifest. ``channel`` limits ``message.in`` and ``reply.render``
        to one channel type.
        """
        if event not in EVENTS:
            raise PluginError(f"unknown event {event!r}; known: {sorted(EVENTS)}")
        if modify and event not in MODIFY_EVENTS:
            raise PluginError(f"{event} cannot be modified")
        if modify and "hook.modify" not in self.manifest.permissions:
            raise PluginError(f"modify hook on {event} needs 'hook.modify' in permissions")

        def register(f):
            self.scope.hooks.append(Hook(self.id, event, f, modify, channel))
            return f

        return register(fn) if fn is not None else register

    def skills(self, path: str = "skills"):
        """Ship the skills under ``path`` (relative to the plugin) with the plugin."""
        skill_dir = (self.dir / path).resolve()
        if not skill_dir.is_dir():
            raise PluginError(f"skills directory not found: {path}")
        self.scope.skill_dirs.append(str(skill_dir))

    def mcp(self, name: str, config: dict):
        """Ship an MCP server, in the same shape as an ``mcp.json`` entry."""
        if not name or not isinstance(config, dict):
            raise PluginError("ctx.mcp() takes a name and a config dict")
        entry = {"name": name, **config}
        if "type" not in entry:
            entry["type"] = "sse" if "url" in entry else "stdio"
        self.scope.mcp_servers.append(entry)

    def channel(self, name: str, factory: Callable):
        """Provide a channel type, selected by ``channel_type`` in config."""
        if not name or not callable(factory):
            raise PluginError("ctx.channel() takes a name and a channel class")
        self.scope.channels[name] = factory

    def provider(self, name: str, factory: Callable):
        """Provide a model provider, selected by ``bot_type`` in config.

        The factory builds an object with the same interface as the built-in
        bots in ``models/``.
        """
        if not name or not callable(factory):
            raise PluginError("ctx.provider() takes a name and a bot class")
        self.scope.providers[name] = factory

    def on_unload(self, fn: Callable):
        """Run ``fn`` when the plugin is disabled, e.g. to stop its threads."""
        self.scope.unload.append(fn)
        return fn
