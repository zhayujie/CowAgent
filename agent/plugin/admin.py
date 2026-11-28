"""``/plugin``: list, install, enable, disable, reload and remove plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.plugin.host import PluginHost

# Installing or enabling a plugin runs code in the kernel, so only the owner's
# own consoles may do it; chat channels can only look.
_MANAGE_CHANNELS = frozenset({"web", "terminal", "console"})

USAGE = (
    "/plugin list\n"
    "/plugin install <git-url | path>\n"
    "/plugin enable <id>\n"
    "/plugin disable <id>\n"
    "/plugin reload <id>\n"
    "/plugin remove <id>"
)


def _can_manage(ev) -> bool:
    if getattr(ev, "is_group", False):
        return False
    return getattr(ev, "channel_type", None) in _MANAGE_CHANNELS


def _format_list(host: "PluginHost") -> str:
    rows = host.describe()
    if not rows:
        return f"No plugins installed. Plugin directory: {host.user_dir}"
    lines = []
    for row in rows:
        state = "on" if row["enabled"] else "off"
        lines.append(f"[{state}] {row['id']} {row['version']}" + (" (built-in)" if row["builtin"] else ""))
        if row["description"]:
            lines.append(f"    {row['description']}")
        provided = [f"{k}: {', '.join(map(str, v))}" for k, v in row["provides"].items()
                    if v and not isinstance(v, int)]
        if row["provides"]["skills"]:
            provided.append(f"skills: {row['provides']['skills']} dir(s)")
        if provided:
            lines.append("    " + "; ".join(provided))
        if row["error"]:
            lines.append(f"    ! {row['error']}")
    return "\n".join(lines)


def _format_permissions(host: "PluginHost", plugin_id: str) -> str:
    rec = host.records.get(plugin_id)
    perms = rec.manifest.permissions if rec else []
    return "Permissions: " + (", ".join(perms) if perms else "none declared")


def handle(host: "PluginHost", args: str, ev) -> str:
    parts = (args or "").split(None, 1)
    action = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else ""

    if action in ("list", "ls"):
        host.discover()
        return _format_list(host)

    if action not in ("install", "enable", "disable", "reload", "remove", "uninstall"):
        return USAGE
    if not _can_manage(ev):
        return "Plugins can only be managed from the web console, the desktop app or the terminal."
    if not target:
        return USAGE

    if action == "install":
        ok, result = host.install(target)
        if not ok:
            return result
        return (f"Installed '{result}' (off). {_format_permissions(host, result)}\n"
                f"Run /plugin enable {result} to turn it on.")
    if action == "enable":
        ok, err = host.enable(target)
        return f"Enabled '{target}'. {_format_permissions(host, target)}" if ok else f"Cannot enable '{target}': {err}"
    if action == "disable":
        ok, err = host.disable(target)
        return f"Disabled '{target}'." if ok else err
    if action == "reload":
        ok, err = host.reload(target)
        return f"Reloaded '{target}'." if ok else f"Cannot reload '{target}': {err}"
    ok, err = host.remove(target)
    return f"Removed '{target}'." if ok else err


def register_admin_command(host: "PluginHost"):
    host.register_kernel_command("plugin", lambda args, ev: handle(host, args, ev), help="manage plugins")
