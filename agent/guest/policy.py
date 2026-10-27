"""What a guest profile may never do, and which changes need the owner.

Two separate questions:

- ``enforce_hard_rules``: settings that are refused whoever asks, the owner in
  the console included: a reference directory that exposes the owner's
  workspace root, home directory, credentials or another profile.
- ``meet``: given the configuration the owner last confirmed and the one on
  disk now, the configuration in force. Every field moves towards the more
  restrictive of the two, so tightening applies at once and widening stays
  pending until the owner confirms it in the console. Editing the file
  directly, by hand or through the main Agent, cannot skip that step.
"""

from __future__ import annotations

import copy
import math
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agent.guest.profile import (
    LIMIT_SPECS,
    NETWORK_TOOLS,
    UNLIMITED_WHEN_ZERO,
    guests_root,
    parse_expires,
    reference_paths,
)

# Files and directories inside an Agent workspace a visitor may never read,
# not even when the owner points a reference directory at them.
_WORKSPACE_PRIVATE = (
    "memory", "guests", "system", "scheduler", "tmp", "runs", "users",
    "AGENT.md", "USER.md", "RULE.md", "MEMORY.md", "BOOTSTRAP.md",
    ".env", "mcp.json",
)
# Credential stores under the home directory.
_HOME_PRIVATE = (
    ".ssh", ".aws", ".gnupg", ".config", ".kube", ".docker", ".netrc",
    ".cow", ".git-credentials", ".npmrc", ".pypirc", "Library/Keychains",
)

def path_key(path: str) -> str:
    """A comparable form of ``path``: symlinks resolved, case folded where the
    file system usually ignores case (so ``~/COW`` cannot slip past ``~/cow``)."""
    real = os.path.normcase(os.path.realpath(os.path.expanduser(path)))
    if sys.platform == "darwin":
        real = real.lower()
    return real


def is_within(path_k: str, root_k: str) -> bool:
    if path_k == root_k:
        return True
    root = root_k if root_k.endswith(os.sep) else root_k + os.sep
    return path_k.startswith(root)


def _workspace_roots() -> List[str]:
    roots: List[str] = []
    try:
        from agent.registry import get_agent_registry

        for profile in get_agent_registry().list(include_disabled=True):
            if profile.workspace:
                roots.append(profile.workspace)
    except Exception:
        pass
    try:
        from common.state_dir import shared_root

        roots.append(str(shared_root()))
    except Exception:
        pass
    return roots


def _data_root() -> Optional[str]:
    try:
        from config import get_data_root

        return get_data_root()
    except Exception:
        return None


def sensitive_locations() -> Tuple[List[str], List[str]]:
    """``(exposed_by_ancestor, no_entry)`` as comparable keys.

    A reference directory may not contain anything in the first list (pointing at the
    home directory would expose ``~/.ssh``), and may not sit inside anything in
    the second.
    """
    home = os.path.expanduser("~")
    workspaces = _workspace_roots()
    data_root = _data_root()
    exposed = [home, guests_root()] + workspaces
    no_entry = [guests_root()]
    if data_root:
        exposed.append(data_root)
        no_entry.append(data_root)
    for ws in workspaces:
        for name in _WORKSPACE_PRIVATE:
            no_entry.append(os.path.join(ws, name))
    for name in _HOME_PRIVATE:
        no_entry.append(os.path.join(home, name))
    exposed.extend(no_entry)
    return (
        sorted({path_key(p) for p in exposed}),
        sorted({path_key(p) for p in no_entry}),
    )


def reference_problem(path: str, locations=None) -> Optional[str]:
    """Why ``path`` may not be a reference directory, or None when it may."""
    exposed, no_entry = locations or sensitive_locations()
    key = path_key(path)
    for item in no_entry:
        if is_within(key, item):
            return "it is inside a private location (workspace state, credentials or guest data)"
    for item in exposed:
        if is_within(item, key):
            return "it contains a private location (home, workspace root, credentials or guest data)"
    return None


def in_no_entry(real_path: str, locations=None) -> bool:
    _, no_entry = locations or sensitive_locations()
    key = path_key(real_path)
    return any(is_within(key, item) for item in no_entry)


def enforce_hard_rules(config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Strip what may never be enabled."""
    cfg = copy.deepcopy(config)
    notices: List[str] = []
    locations = sensitive_locations()
    kept = []
    for ref in cfg.get("references") or []:
        path = ref["path"]
        problem = reference_problem(path, locations)
        if problem:
            notices.append(f"reference {path} refused: {problem}")
        elif not os.path.exists(path):
            notices.append(f"reference {path} does not exist")
        else:
            kept.append(ref)
    cfg["references"] = kept
    return cfg, notices


def _limit(value: int, key: str) -> float:
    if key in UNLIMITED_WHEN_ZERO and value == 0:
        return math.inf
    return value


def _expiry(value: str) -> float:
    ts = parse_expires(value or "")
    return math.inf if ts is None else ts


def _covered(path: str, roots: Iterable[str]) -> bool:
    key = path_key(path)
    return any(is_within(key, path_key(root)) for root in roots)


def meet(confirmed: Dict[str, Any], current: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The configuration in force, and a line per change still waiting for
    the owner. Cosmetic fields (name, welcome, suggested questions,
    branding) always follow the file."""
    eff = copy.deepcopy(current)
    pending: List[str] = []

    for key in ("tools", "skills"):
        allowed = set(confirmed.get(key) or [])
        added = [x for x in current.get(key) or [] if x not in allowed]
        if added:
            pending.append(f"{key}: add {', '.join(added)}")
            eff[key] = [x for x in current.get(key) or [] if x in allowed]

    confirmed_paths = reference_paths(confirmed)
    added_paths = [p for p in reference_paths(current) if not _covered(p, confirmed_paths)]
    if added_paths:
        pending.append(f"references: add {', '.join(added_paths)}")
        eff["references"] = [r for r in current.get("references") or [] if r["path"] not in added_paths]

    c_net, n_net = confirmed.get("network") or {}, current.get("network") or {}
    if n_net.get("enabled") and not c_net.get("enabled"):
        pending.append("network: enable")
        eff["network"] = {"enabled": False, "allow_domains": list(n_net.get("allow_domains") or [])}
    elif n_net.get("enabled"):
        c_domains = list(c_net.get("allow_domains") or [])
        n_domains = list(n_net.get("allow_domains") or [])
        if c_domains:
            if not n_domains:
                pending.append("network: allow any domain")
                eff["network"]["allow_domains"] = c_domains
            else:
                added = [d for d in n_domains if d not in c_domains]
                if added:
                    pending.append(f"network: allow {', '.join(added)}")
                    kept = [d for d in n_domains if d in c_domains]
                    eff["network"]["allow_domains"] = kept
                    if not kept:
                        eff["network"]["enabled"] = False

    c_limits, n_limits = confirmed.get("limits") or {}, current.get("limits") or {}
    for key, spec in LIMIT_SPECS.items():
        c_val = c_limits.get(key, spec[2])
        n_val = n_limits.get(key, spec[2])
        if _limit(n_val, key) > _limit(c_val, key):
            pending.append(f"limits.{key}: {c_val} -> {n_val}")
            eff["limits"][key] = c_val

    if _expiry(current.get("expires_at")) > _expiry(confirmed.get("expires_at")):
        pending.append(f"expires_at: {confirmed.get('expires_at') or 'never'} -> {current.get('expires_at') or 'never'}")
        eff["expires_at"] = confirmed.get("expires_at") or ""

    c_access, n_access = confirmed.get("access") or {}, current.get("access") or {}
    if c_access.get("password_required") and not n_access.get("password_required"):
        pending.append("access: drop the password")
        eff["access"]["password_required"] = True
    c_origins = c_access.get("allowed_origins") or []
    added = [o for o in n_access.get("allowed_origins") or [] if o not in c_origins]
    if added:
        pending.append(f"access.allowed_origins: add {', '.join(added)}")
        eff["access"]["allowed_origins"] = [o for o in n_access.get("allowed_origins") or [] if o in c_origins]

    for key in ("provider", "model"):
        if (current.get(key) or "") != (confirmed.get(key) or ""):
            pending.append(f"{key}: {confirmed.get(key) or 'default'} -> {current.get(key) or 'default'}")
            eff[key] = confirmed.get(key) or ""

    return eff, pending


def offered_tools(config: Dict[str, Any]) -> List[str]:
    """Tools a visitor is actually given under ``config``."""
    tools = list(config.get("tools") or [])
    if not (config.get("network") or {}).get("enabled"):
        tools = [t for t in tools if t not in NETWORK_TOOLS]
    return tools
