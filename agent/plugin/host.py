"""Plugin host: discovery, lifecycle, registries and guarded execution.

Plugins live in two places, loaded the same way:
  - ``builtin_plugins/<id>/`` in the repository
  - ``<workspace>/system/plugins/<id>/`` for plugins the owner installed

Which plugins are on, and their config overrides, are kept in
``<workspace>/system/plugins.json``. Plugins run in the kernel's process and
are trusted code: the guards here contain faults (a hook that raises or hangs
is skipped, and a plugin that keeps failing is switched off), they are not a
security sandbox.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from common.log import logger
from common import runtime_identity

from agent.plugin.context import (
    MODIFY_EVENTS,
    Command,
    Hook,
    PluginContext,
    PluginError,
    Scope,
)
from agent.plugin.manifest import ID_RE, KNOWN_PERMISSIONS, Manifest, ManifestError, load_manifest

HOOK_TIMEOUT = 2.0
COMMAND_TIMEOUT = 30.0
FAILURE_LIMIT = 3
INSTALL_TIMEOUT = 120

_MODULE_PREFIX = "cow_plugins"
_REPO_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_DIR = _REPO_ROOT / "builtin_plugins"


class HookEvent:
    """The object a hook or command handler receives. Fields are attributes."""

    def __init__(self, name: str, **fields):
        self.name = name
        self.__dict__.update(fields)

    def __repr__(self):
        return f"HookEvent({self.name})"


@dataclass
class PluginRecord:
    manifest: Manifest
    dir: Path
    builtin: bool
    enabled: bool = False
    error: str = ""
    failures: int = 0


def _state_file() -> Path:
    from common.state_dir import system_dir
    return system_dir() / "plugins.json"


def user_plugins_dir() -> Path:
    from common.state_dir import system_dir
    return system_dir() / "plugins"


# Answered by the bundled command plugin; used until that module is loaded.
_BUILTIN_COMMANDS = frozenset({
    "help", "version", "status", "logs", "start", "stop", "restart", "cancel",
    "skill", "context", "config", "tasks", "knowledge", "memory", "compact",
    "clear", "install-browser", "steer",
})


def _reserved_commands() -> frozenset:
    """Command names the kernel and the bundled command plugin already answer."""
    names = {"plugin"} | _BUILTIN_COMMANDS
    # Read from the loaded module rather than importing it: the legacy plugin
    # manager must be the one to import it, or its registration breaks.
    module = sys.modules.get("plugins.cow_cli.cow_cli")
    if module is not None:
        names.update(getattr(module, "KNOWN_COMMANDS", ()))
        names.update(getattr(module, "DEFAULT_ALIASES", {}))
    return frozenset(names)


class PluginHost:
    def __init__(self, builtin_dir: Optional[Path] = None, user_dir: Optional[Path] = None,
                 state_file: Optional[Path] = None):
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self._state_path = state_file
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="plugin")
        self.records: Dict[str, PluginRecord] = {}
        self._scopes: Dict[str, Scope] = {}
        self.loaded = False
        self.revision = 0
        self.mcp_revision = 0
        self._kernel_commands: Dict[str, Command] = {}
        self._rebuild()

    # -- paths and state -------------------------------------------------

    @property
    def builtin_dir(self) -> Path:
        return self._builtin_dir or BUILTIN_DIR

    @property
    def user_dir(self) -> Path:
        return self._user_dir or user_plugins_dir()

    @property
    def state_path(self) -> Path:
        return self._state_path or _state_file()

    def _read_state(self) -> dict:
        try:
            with open(self.state_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("plugins"), dict):
                return data
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"[Plugin] cannot read {self.state_path}: {e}")
        return {"plugins": {}}

    def _write_state(self, mutate: Callable[[dict], None]):
        with self._lock:
            data = self._read_state()
            mutate(data["plugins"])
            from common.atomic_write import write_text_atomic
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(self.state_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def _saved(self, plugin_id: str) -> dict:
        entry = self._read_state()["plugins"].get(plugin_id)
        return entry if isinstance(entry, dict) else {}

    # -- discovery -------------------------------------------------------

    def discover(self) -> Dict[str, PluginRecord]:
        """Scan both plugin roots. A user plugin shadows a builtin one of the same id."""
        found: Dict[str, PluginRecord] = {}
        for root, builtin in ((self.builtin_dir, True), (self.user_dir, False)):
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith((".", "_")):
                    continue
                try:
                    manifest = load_manifest(child)
                except ManifestError as e:
                    logger.warning(f"[Plugin] skipped {child}: {e}")
                    continue
                unknown = set(manifest.permissions) - KNOWN_PERMISSIONS
                if unknown:
                    logger.warning(f"[Plugin] {manifest.id}: unknown permissions {sorted(unknown)}")
                found[manifest.id] = PluginRecord(manifest, child, builtin)
        with self._lock:
            for plugin_id, rec in found.items():
                old = self.records.get(plugin_id)
                if old is not None:
                    rec.enabled, rec.error, rec.failures = old.enabled, old.error, old.failures
            for plugin_id in [p for p in self.records if p not in found]:
                if plugin_id in self._scopes:
                    self._revoke(plugin_id)
            self.records = found
        return found

    def load_all(self):
        """Discover plugins and enable the ones switched on. Never raises."""
        try:
            self.discover()
            state = self._read_state()["plugins"]
            for plugin_id, rec in list(self.records.items()):
                saved = state.get(plugin_id) if isinstance(state.get(plugin_id), dict) else {}
                wanted = saved.get("enabled", rec.builtin and rec.manifest.default_enabled)
                if wanted:
                    self.enable(plugin_id, persist=False)
            active = [p for p, r in self.records.items() if r.enabled]
            if self.records:
                logger.info(f"[Plugin] {len(active)}/{len(self.records)} plugin(s) enabled: {active}")
        except Exception as e:
            logger.warning(f"[Plugin] loading failed: {e}")
        finally:
            self.loaded = True

    # -- lifecycle -------------------------------------------------------

    def _import(self, rec: PluginRecord) -> types.ModuleType:
        plugin_id = rec.manifest.id
        pkg_name = f"{_MODULE_PREFIX}.{plugin_id.replace('-', '_')}"
        self._drop_modules(pkg_name)

        if _MODULE_PREFIX not in sys.modules:
            root = types.ModuleType(_MODULE_PREFIX)
            root.__path__ = []
            sys.modules[_MODULE_PREFIX] = root

        init_file = rec.dir / "__init__.py"
        entry = rec.manifest.entry or ("__init__.py" if init_file.is_file() else "main.py")
        entry_file = (rec.dir / entry).resolve()
        if not entry_file.is_file() or rec.dir.resolve() not in entry_file.parents:
            raise PluginError(f"entry file not found: {entry}")

        # Load the plugin directory as a package so its modules can import
        # each other relatively.
        if init_file.is_file():
            pkg_spec = importlib.util.spec_from_file_location(
                pkg_name, init_file, submodule_search_locations=[str(rec.dir)],
            )
            package = importlib.util.module_from_spec(pkg_spec)
            sys.modules[pkg_name] = package
            pkg_spec.loader.exec_module(package)
            if entry_file == init_file.resolve():
                return package
        else:
            package = types.ModuleType(pkg_name)
            package.__path__ = [str(rec.dir)]
            sys.modules[pkg_name] = package

        mod_name = f"{pkg_name}.{entry_file.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, entry_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _drop_modules(pkg_name: str):
        for name in [n for n in sys.modules if n == pkg_name or n.startswith(pkg_name + ".")]:
            sys.modules.pop(name, None)

    def _config_for(self, rec: PluginRecord) -> Dict[str, Any]:
        config = rec.manifest.config_defaults()
        saved = self._saved(rec.manifest.id).get("config")
        if isinstance(saved, dict):
            config.update(saved)
        return config

    def enable(self, plugin_id: str, persist: bool = True) -> Tuple[bool, str]:
        with self._lock:
            rec = self.records.get(plugin_id)
            if rec is None:
                self.discover()
                rec = self.records.get(plugin_id)
            if rec is None:
                return False, f"plugin '{plugin_id}' not found"
            if plugin_id in self._scopes:
                self._revoke(plugin_id)

            ctx = PluginContext(
                rec.manifest, rec.dir, self.user_dir / ".data" / plugin_id, self._config_for(rec)
            )
            try:
                module = self._import(rec)
                apply = getattr(module, "apply", None)
                if not callable(apply):
                    raise PluginError("entry module has no apply(ctx)")
                apply(ctx)
                self._check_conflicts(plugin_id, ctx.scope)
            except Exception as e:
                rec.enabled = False
                rec.error = f"{type(e).__name__}: {e}"
                self._run_unload(plugin_id, ctx.scope)
                logger.warning(f"[Plugin] {plugin_id} failed to enable: {rec.error}")
                return False, rec.error

            self._scopes[plugin_id] = ctx.scope
            rec.enabled, rec.error, rec.failures = True, "", 0
            self._rebuild()
        if persist:
            self._write_state(lambda p: p.setdefault(plugin_id, {}).update(enabled=True))
        self._after_change(ctx.scope)
        logger.info(f"[Plugin] enabled {plugin_id} {rec.manifest.version}")
        return True, ""

    def disable(self, plugin_id: str, persist: bool = True, reason: str = "") -> Tuple[bool, str]:
        with self._lock:
            rec = self.records.get(plugin_id)
            if rec is None:
                return False, f"plugin '{plugin_id}' not found"
            scope = self._scopes.get(plugin_id)
            if scope is not None:
                self._revoke(plugin_id)
            rec.enabled = False
            if reason:
                rec.error = reason
        if persist:
            self._write_state(lambda p: p.setdefault(plugin_id, {}).update(enabled=False))
        if scope is not None:
            self._after_change(scope)
        logger.info(f"[Plugin] disabled {plugin_id}" + (f": {reason}" if reason else ""))
        return True, ""

    def reload(self, plugin_id: str) -> Tuple[bool, str]:
        self.discover()
        return self.enable(plugin_id, persist=False)

    def _revoke(self, plugin_id: str):
        scope = self._scopes.pop(plugin_id, None)
        if scope is None:
            return
        self._run_unload(plugin_id, scope)
        self._drop_modules(f"{_MODULE_PREFIX}.{plugin_id.replace('-', '_')}")
        self._rebuild()

    def _run_unload(self, plugin_id: str, scope: Scope):
        for fn in scope.unload:
            try:
                fn()
            except Exception as e:
                logger.warning(f"[Plugin] {plugin_id} unload hook failed: {e}")

    def _check_conflicts(self, plugin_id: str, scope: Scope):
        builtin_tools = set()
        try:
            from agent.tools import ToolManager
            builtin_tools = set(ToolManager().tool_classes)
        except Exception:
            pass
        try:
            # Names the permission policy trusts by name, e.g. memory tools
            # that are not in the tool registry.
            from agent.permission.policy import _KNOWN_TOOLS
            builtin_tools |= set(_KNOWN_TOOLS)
        except Exception:
            pass
        reserved = _reserved_commands()
        for other_id, other in self._scopes.items():
            if other_id == plugin_id:
                continue
            for kind, mine, theirs in (
                ("tool", scope.tools, other.tools),
                ("command", scope.commands, other.commands),
                ("channel", scope.channels, other.channels),
                ("provider", scope.providers, other.providers),
            ):
                clash = set(mine) & set(theirs)
                if clash:
                    raise PluginError(f"{kind} {sorted(clash)} already provided by plugin '{other_id}'")
        clash = set(scope.tools) & builtin_tools
        if clash:
            raise PluginError(f"tool {sorted(clash)} is a built-in tool")
        clash = set(scope.commands) & reserved
        if clash:
            raise PluginError(f"command {sorted(clash)} is a built-in command")

    def _rebuild(self):
        """Recompute the lookup tables. Readers take the current objects without locking."""
        tools, commands, channels, providers, tool_owner = {}, dict(self._kernel_commands), {}, {}, {}
        hooks: Dict[str, List[Hook]] = {}
        skill_dirs, mcp = [], []
        for plugin_id, scope in self._scopes.items():
            for name, factory in scope.tools.items():
                tools[name] = factory
                tool_owner[name] = plugin_id
            commands.update(scope.commands)
            channels.update(scope.channels)
            providers.update(scope.providers)
            for hook in scope.hooks:
                hooks.setdefault(hook.event, []).append(hook)
            skill_dirs.extend(scope.skill_dirs)
            mcp.extend(scope.mcp_servers)
        self.tools = tools
        self.tool_owner = tool_owner
        self.commands = commands
        self.channels = channels
        self.providers = providers
        self.hooks = {event: tuple(items) for event, items in hooks.items()}
        self.skill_dirs = tuple(skill_dirs)
        mcp = tuple(mcp)
        if mcp != getattr(self, "mcp_servers", ()):
            self.mcp_revision += 1
        self.mcp_servers = mcp
        self.revision += 1

    def _after_change(self, scope: Scope):
        """Let long-lived consumers pick up MCP servers that came or went."""
        if not scope.mcp_servers:
            return
        try:
            from agent.tools import ToolManager
            for tm in ToolManager.instances():
                tm.refresh_mcp_if_changed()
        except Exception as e:
            logger.debug(f"[Plugin] MCP refresh skipped: {e}")

    def register_kernel_command(self, name: str, fn: Callable, help: str = ""):
        with self._lock:
            self._kernel_commands[name] = Command("kernel", name, fn, help)
            self._rebuild()

    # -- install / remove ------------------------------------------------

    def install(self, source: str) -> Tuple[bool, str]:
        """Install from a local directory or a git URL. The plugin starts disabled."""
        source = (source or "").strip()
        if not source:
            return False, "usage: /plugin install <git-url | path>"
        self.user_dir.mkdir(parents=True, exist_ok=True)
        staging = self.user_dir / f".install-{int(time.time() * 1000)}"
        try:
            local = Path(os.path.expanduser(source))
            if local.is_dir():
                shutil.copytree(local, staging, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            elif source.startswith(("http://", "https://", "git@")) or source.endswith(".git"):
                proc = subprocess.run(
                    ["git", "clone", "--depth", "1", source, str(staging)],
                    capture_output=True, text=True, timeout=INSTALL_TIMEOUT,
                )
                if proc.returncode != 0:
                    return False, f"git clone failed: {(proc.stderr or proc.stdout).strip()[-300:]}"
                shutil.rmtree(staging / ".git", ignore_errors=True)
            else:
                return False, f"not a directory or git URL: {source}"

            manifest = load_manifest(staging)
            target = self.user_dir / manifest.id
            if target.exists():
                return False, f"plugin '{manifest.id}' is already installed; remove it first"
            staging.rename(target)
        except FileNotFoundError as e:
            return False, f"install failed: {e}"
        except (ManifestError, subprocess.TimeoutExpired, OSError) as e:
            return False, f"install failed: {e}"
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        self.discover()
        return True, manifest.id

    def remove(self, plugin_id: str) -> Tuple[bool, str]:
        rec = self.records.get(plugin_id)
        if rec is None:
            return False, f"plugin '{plugin_id}' not found"
        if rec.builtin:
            return False, f"'{plugin_id}' is built in; disable it instead"
        self.disable(plugin_id, persist=False)
        target = rec.dir.resolve()
        if target.parent != self.user_dir.resolve() or not ID_RE.match(target.name):
            return False, f"refusing to delete {target}"
        shutil.rmtree(target, ignore_errors=True)
        shutil.rmtree(self.user_dir / ".data" / plugin_id, ignore_errors=True)
        self._write_state(lambda p: p.pop(plugin_id, None))
        self.discover()
        return True, ""

    # -- guarded execution -----------------------------------------------

    def call(self, plugin_id: str, fn: Callable, *args, timeout: float = HOOK_TIMEOUT) -> Tuple[bool, Any]:
        """Run plugin code with a timeout, counting failures toward the breaker.

        A timed-out call cannot be killed; it is abandoned and keeps running
        on its worker thread, and its result is ignored.
        """
        future = runtime_identity.submit(self._pool, fn, *args)
        try:
            result = future.result(timeout=timeout)
        except FutureTimeout:
            self._failed(plugin_id, f"timed out after {timeout:g}s")
            return False, None
        except Exception as e:
            self._failed(plugin_id, f"{type(e).__name__}: {e}")
            return False, None
        self._succeeded(plugin_id)
        return True, result

    def observe(self, plugin_id: str, fn: Callable, *args):
        future = runtime_identity.submit(self._pool, fn, *args)

        def _done(f):
            err = f.exception()
            if err is None:
                self._succeeded(plugin_id)
            else:
                self._failed(plugin_id, f"{type(err).__name__}: {err}")

        future.add_done_callback(_done)

    def _succeeded(self, plugin_id: str):
        rec = self.records.get(plugin_id)
        if rec is not None and rec.failures:
            rec.failures = 0

    def _failed(self, plugin_id: str, reason: str):
        rec = self.records.get(plugin_id)
        if rec is None:
            return
        rec.failures += 1
        rec.error = reason
        logger.warning(f"[Plugin] {plugin_id} failed ({rec.failures}/{FAILURE_LIMIT}): {reason}")
        if rec.failures >= FAILURE_LIMIT and rec.enabled:
            self.disable(
                plugin_id,
                reason=f"switched off after {rec.failures} consecutive failures, last: {reason}",
            )

    def run_hooks(self, event: str, fields: dict, mutable: Tuple[str, ...] = (),
                  channel_type: Optional[str] = None) -> dict:
        """Run every hook on ``event``. Modify hooks run in order, each on its
        own copy of the fields; observe hooks get a snapshot in the background."""
        for hook in self.hooks.get(event, ()):
            if hook.channel and hook.channel != channel_type:
                continue
            fields = self.run_hook(hook, fields, mutable)
        return fields

    def run_hook(self, hook: Hook, fields: dict, mutable: Tuple[str, ...] = ()) -> dict:
        if not hook.modify or hook.event not in MODIFY_EVENTS:
            self.observe(hook.plugin_id, hook.fn, HookEvent(hook.event, **_snapshot(fields)))
            return fields
        ev = HookEvent(hook.event, **_snapshot(fields))
        ok, _ = self.call(hook.plugin_id, hook.fn, ev)
        if ok:
            fields = dict(fields)
            for key in mutable:
                fields[key] = getattr(ev, key, fields.get(key))
        return fields

    def collect(self, event: str, fields: dict) -> List[Tuple[str, Any]]:
        """Run hooks whose return value is the contribution, e.g. prompt sections."""
        out = []
        for hook in self.hooks.get(event, ()):
            ok, result = self.call(hook.plugin_id, hook.fn, HookEvent(event, **_snapshot(fields)))
            if ok and result:
                out.append((hook.plugin_id, result))
        return out

    # -- views -----------------------------------------------------------

    def describe(self) -> List[dict]:
        rows = []
        for plugin_id, rec in sorted(self.records.items()):
            scope = self._scopes.get(plugin_id) or Scope()
            rows.append({
                "id": plugin_id,
                "name": rec.manifest.title,
                "version": rec.manifest.version,
                "description": rec.manifest.description,
                "builtin": rec.builtin,
                "enabled": rec.enabled,
                "error": rec.error,
                "permissions": list(rec.manifest.permissions),
                "provides": {
                    "tools": sorted(scope.tools),
                    "commands": sorted(scope.commands),
                    "hooks": sorted({h.event for h in scope.hooks}),
                    "skills": len(scope.skill_dirs),
                    "mcp": [s.get("name") for s in scope.mcp_servers],
                    "channels": sorted(scope.channels),
                    "providers": sorted(scope.providers),
                },
            })
        return rows


def _snapshot(fields: dict) -> dict:
    out = {}
    for key, value in fields.items():
        if isinstance(value, (dict, list)):
            try:
                value = copy.deepcopy(value)
            except Exception:
                pass
        out[key] = value
    return out
