"""Guard for CowAgent-managed MCP config files.

``mcp.json`` is hot-reloaded into stdio subprocesses. The write/edit tools
must not be able to change those files (issue #3231). Scope is the paths
CowAgent actually resolves: ``~/cow/mcp.json``, ``~/.cow/mcp.json``, the
configured ``agent_workspace`` copy, every ``AgentProfile.workspace`` from
the agent registry (and ``mcp_config_file`` for each), and per-agent copies
one or two levels under those roots.

A path is protected if the lexical normalized path looks like a managed
mcp.json, or if it resolves to the same file as a known managed mcp.json.
The lexical candidate is not realpath'd away, so a symlink named mcp.json
under a protected root cannot be used to overwrite its target.
"""

import os

from common.utils import expand_path

MCP_CONFIG_DENIED_MESSAGE = (
    "Error: writing to mcp.json is not allowed. MCP server config is "
    "protected against tool modification; edit it outside the agent."
)


def _fallback_roots():
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
    return roots


def _registry_workspaces():
    try:
        from agent.registry import get_agent_registry
        return [
            profile.workspace
            for profile in get_agent_registry().list(include_disabled=True)
            if profile.workspace
        ]
    except Exception:
        return []


def _workspace_roots():
    """Fallback roots plus every Agent workspace ToolManager can load from.

    ``~/cow``, ``~/.cow``, and ``agent_workspace`` stay as fallbacks when the
    registry is not up yet.
    """
    return _fallback_roots() + _registry_workspaces()


def _protected_roots():
    roots = []
    seen = set()
    for root in _workspace_roots():
        variants = [os.path.normpath(root)]
        try:
            variants.append(os.path.realpath(root))
        except OSError:
            pass
        for variant in variants:
            if variant not in seen:
                seen.add(variant)
                roots.append(variant)
    return roots


def _known_mcp_paths(roots):
    """Explicit managed mcp.json paths, including ToolManager's load path."""
    paths = []
    seen = set()

    def add(path):
        path = str(path)
        if path and path not in seen:
            seen.add(path)
            paths.append(path)

    for root in roots:
        add(os.path.join(root, "mcp.json"))
    try:
        from common.state_dir import mcp_config_file
        for workspace in _registry_workspaces():
            add(mcp_config_file(base=workspace))
    except Exception:
        pass
    return paths


def _is_managed_mcp_file(path: str, roots) -> bool:
    if os.path.basename(path).lower() != "mcp.json":
        return False
    parent = os.path.dirname(path)
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
    try:
        lexical = os.path.normpath(absolute_path)
    except OSError:
        lexical = absolute_path

    roots = _protected_roots()
    # (a) Lexical path looks like a managed mcp.json. Do not realpath this
    # candidate: a symlink named mcp.json under a protected root must still
    # match on basename/parent.
    if _is_managed_mcp_file(lexical, roots):
        return True

    try:
        path_real = os.path.realpath(absolute_path)
    except OSError:
        path_real = lexical

    # (b) Writing through or to the realpath of a known managed mcp.json.
    for managed in _known_mcp_paths(roots):
        try:
            managed_real = os.path.realpath(managed)
        except OSError:
            managed_real = os.path.normpath(managed)
        if path_real == managed_real:
            return True
    return False
