"""Guard for CowAgent-managed MCP config files.

``mcp.json`` is hot-reloaded into stdio subprocesses. The write/edit tools
must not be able to change those files (issue #3231). Scope is the paths
CowAgent actually resolves: ``~/cow/mcp.json``, ``~/.cow/mcp.json``, the
configured ``agent_workspace`` copy, and per-agent copies one or two levels
under those roots. Comparisons use realpath so a workspace symlink cannot
bypass the check.
"""

import os

from common.utils import expand_path

MCP_CONFIG_DENIED_MESSAGE = (
    "Error: writing to mcp.json is not allowed. MCP server config is "
    "protected against tool modification; edit it outside the agent."
)


def _protected_roots():
    roots = [
        expand_path("~/cow"),
        expand_path("~/.cow"),
    ]
    try:
        from config import conf
        ws = conf().get("agent_workspace")
        if ws:
            roots.append(expand_path(str(ws)))
    except Exception:
        pass
    real_roots = []
    seen = set()
    for root in roots:
        try:
            real = os.path.realpath(root)
        except OSError:
            real = os.path.normpath(root)
        if real not in seen:
            seen.add(real)
            real_roots.append(real)
    return real_roots


def _is_managed_mcp_file(real: str, roots) -> bool:
    if os.path.basename(real).lower() != "mcp.json":
        return False
    parent = os.path.dirname(real)
    for root in roots:
        if parent == root:
            return True
        # Per-agent workspace: {root}/{agent_id}/mcp.json
        if os.path.dirname(parent) == root:
            return True
        # Multi-agent layout: {root}/agents/{agent_id}/mcp.json
        grandparent = os.path.dirname(parent)
        if os.path.basename(grandparent) == "agents" and os.path.dirname(grandparent) == root:
            return True
    return False


def is_mcp_config_path(absolute_path: str) -> bool:
    """Return True if *absolute_path* is a CowAgent-managed mcp.json."""
    candidates = set()
    try:
        candidates.add(os.path.normpath(absolute_path))
        candidates.add(os.path.realpath(absolute_path))
    except OSError:
        candidates.add(absolute_path)

    roots = _protected_roots()
    for candidate in candidates:
        try:
            real = os.path.realpath(candidate)
        except OSError:
            real = os.path.normpath(candidate)
        if _is_managed_mcp_file(real, roots):
            return True
    return False
