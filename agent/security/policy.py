"""
The capability policy: what each trust level is allowed to do.

This is the part of the fix that actually holds. Everything the agent is told
in its system prompt is advisory - a sufficiently well-crafted message can talk
a model out of any instruction it was given. The rules here are ordinary Python
running between the model's decision and the tool's side effect, so they cannot
be argued with.

Guests get a default-deny capability set. The allowlist is small and explicit,
which matters most for MCP: tools loaded from a third-party server have unknown
side effects, so an unrecognised tool name is refused rather than assumed safe.

Owners keep the behaviour they have today. The only checks that apply to them
are the secret-material path guard and the destructive-command analyzer, both
of which exist to catch instructions that were *injected* into the owner's
session rather than typed by the owner.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Set

from common.log import logger
from common.utils import expand_path

from agent.security import commands as cmd_rules
from agent.security import paths as path_rules
from agent.security.trust import SecurityContext, TrustLevel, current_security_context

#: Tools a guest may call at all. Everything else - including any MCP tool - is
#: refused. Note what is absent: bash (arbitrary code execution), env_config
#: (the owner's API keys), scheduler (persistence), and the memory tools (the
#: owner's private notes, which have nothing to do with the guest's request).
_GUEST_ALLOWED_TOOLS: Set[str] = {
    "read", "ls", "search_files", "write", "edit",
    "web_search", "web_fetch", "vision", "send",
}

#: Tools no one but the owner may call, at any trust level below OWNER.
_OWNER_ONLY_TOOLS: Set[str] = {
    "env_config",       # reads and writes the API-key store
    "evolution_undo",   # rewrites the agent's own configuration
}

#: Tools whose arguments are filesystem paths that must stay inside the
#: workspace when the requester is not the owner.
_FILESYSTEM_TOOLS: Set[str] = {
    "read", "write", "edit", "ls", "search_files", "send",
}

_DENY_TOOL_MESSAGE = (
    "Error: The '{tool}' tool is not available for this request.\n"
    "This request came from {who}, who is not the owner of the machine this agent runs on, "
    "so tools that can execute code, reach the owner's private data, or change the agent's "
    "configuration are disabled.\n"
    "Tell the requester plainly that you cannot do this, and do not look for another tool "
    "that achieves the same effect. If they should have this access, the owner needs to add "
    "them to security_owner_users in the CowAgent config."
)


@dataclass
class Decision:
    """The outcome of a security check for one tool call."""

    allowed: bool
    #: Message handed back to the model when the call is refused.
    message: str = ""
    #: Short tag recorded in the audit log.
    category: str = ""
    #: True when the call was refused only pending explicit user approval.
    needs_confirmation: bool = False
    details: dict = field(default_factory=dict)

    @classmethod
    def allow(cls) -> "Decision":
        return cls(allowed=True)

    @classmethod
    def deny(cls, message: str, category: str, **details) -> "Decision":
        return cls(allowed=False, message=message, category=category, details=details)

    @classmethod
    def confirm(cls, message: str, category: str, **details) -> "Decision":
        return cls(
            allowed=False,
            message=message,
            category=category,
            needs_confirmation=True,
            details=details,
        )


def workspace_root(cwd: Optional[str] = None) -> str:
    """The directory a non-owner request is confined to."""
    from config import conf

    if cwd:
        return os.path.realpath(expand_path(cwd))
    configured = conf().get("agent_workspace", "~/cow") or "~/cow"
    return os.path.realpath(expand_path(configured))


def _extra_allowed_roots() -> list:
    """Additional roots the owner opted into sharing with non-owners."""
    from config import conf

    roots = conf().get("security_guest_allowed_paths", []) or []
    if isinstance(roots, str):
        roots = [roots]
    resolved = []
    for root in roots:
        try:
            resolved.append(os.path.realpath(expand_path(str(root))))
        except Exception:
            continue
    return resolved


def _guest_tool_allowlist() -> Set[str]:
    from config import conf

    allowed = set(_GUEST_ALLOWED_TOOLS)
    extra = conf().get("security_guest_extra_tools", []) or []
    if isinstance(extra, str):
        extra = [extra]
    allowed |= {str(name).strip() for name in extra if str(name).strip()}
    return allowed - _OWNER_ONLY_TOOLS


def evaluate_tool_call(
    tool_name: str,
    args: dict,
    ctx: Optional[SecurityContext] = None,
    cwd: Optional[str] = None,
) -> Decision:
    """Decide whether *tool_name* may run with *args* under *ctx*.

    Args:
        tool_name: the tool about to execute.
        args: the arguments the model produced.
        ctx: security context; defaults to the one bound to this request.
        cwd: the tool's working directory, used as the confinement root.

    Returns:
        A :class:`Decision`. ``allowed=False`` means the tool must not run.
    """
    from config import conf

    if not conf().get("security_enabled", True):
        return Decision.allow()

    ctx = ctx or current_security_context()
    args = args if isinstance(args, dict) else {}
    tool_name = (tool_name or "").strip()

    # 1. Capability gate - which tools exist at all for this requester.
    decision = _check_capability(tool_name, ctx)
    if not decision.allowed:
        return decision

    # 2. Secret material - applies at every trust level, owner included.
    decision = _check_sensitive_paths(tool_name, args, ctx, cwd)
    if not decision.allowed:
        return decision

    # 3. Confinement - non-owners cannot leave the workspace.
    if not ctx.is_privileged:
        decision = _check_confinement(tool_name, args, ctx, cwd)
        if not decision.allowed:
            return decision

    # 4. Shell command analysis.
    if tool_name in ("bash", "terminal"):
        decision = _check_shell(args, ctx)
        if not decision.allowed:
            return decision

    # 5. Local-file URL schemes (a browser can read the disk via file://).
    decision = _check_url_scheme(tool_name, args, ctx)
    if not decision.allowed:
        return decision

    return Decision.allow()


def _check_capability(tool_name: str, ctx: SecurityContext) -> Decision:
    # Case A - a request we could not attribute to any identified sender. This
    # is a structural failure (missing / unparseable identity), not an
    # unauthorized-but-known person, so it fails closed: no tool of any kind
    # may run, not even a conversational one. The category is "identity.missing"
    # on purpose - a caller, retry loop, or dashboard must be able to tell this
    # apart from a real stranger's "capability.not_allowlisted" refusal, because
    # the two call for different responses (fix the request vs. deny the user).
    if ctx.trust <= TrustLevel.UNTRUSTED:
        return Decision.deny(
            "Error: This request could not be attributed to an identified sender "
            "(missing or unparseable sender identity), so no action was taken. "
            "CowAgent does not act on requests it cannot attribute.",
            "identity.missing",
            identity_status=getattr(ctx, "identity_status", "unidentified"),
        )

    if ctx.trust >= TrustLevel.OWNER:
        return Decision.allow()

    if tool_name in _OWNER_ONLY_TOOLS:
        return Decision.deny(
            _DENY_TOOL_MESSAGE.format(tool=tool_name, who=ctx.describe()),
            "capability.owner_only",
            tool=tool_name,
        )

    if ctx.trust >= TrustLevel.TRUSTED:
        # Trusted users keep shell and broad filesystem access; they were
        # named by the owner precisely so they could do real work.
        return Decision.allow()

    if tool_name not in _guest_tool_allowlist():
        return Decision.deny(
            _DENY_TOOL_MESSAGE.format(tool=tool_name, who=ctx.describe()),
            "capability.not_allowlisted",
            tool=tool_name,
        )

    return Decision.allow()


def _check_sensitive_paths(
    tool_name: str, args: dict, ctx: SecurityContext, cwd: Optional[str]
) -> Decision:
    for raw in path_rules.extract_paths(tool_name, args):
        absolute = path_rules.resolve_against(raw, cwd)
        kind = path_rules.sensitive_path_kind(absolute)
        if kind and path_rules.is_sensitive_path(absolute):
            return Decision.deny(
                path_rules.DENIED_SENSITIVE.format(path=raw, kind=kind),
                "path.sensitive",
                path=absolute,
                kind=kind,
            )
    return Decision.allow()


def _check_confinement(
    tool_name: str, args: dict, ctx: SecurityContext, cwd: Optional[str]
) -> Decision:
    if tool_name not in _FILESYSTEM_TOOLS:
        return Decision.allow()

    root = workspace_root(cwd)
    allowed_roots = [root] + _extra_allowed_roots()

    for raw in path_rules.extract_paths(tool_name, args):
        absolute = path_rules.resolve_against(raw, cwd)
        if not any(path_rules.is_within_root(absolute, candidate) for candidate in allowed_roots):
            return Decision.deny(
                path_rules.DENIED_OUTSIDE_WORKSPACE.format(
                    who=ctx.describe(), root=root, path=raw
                ),
                "path.outside_workspace",
                path=absolute,
                root=root,
            )
    return Decision.allow()


def _check_shell(args: dict, ctx: SecurityContext) -> Decision:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return Decision.allow()

    risk = cmd_rules.inspect_command(command)
    if risk is None:
        return Decision.allow()

    message = cmd_rules.format_refusal(risk)
    if risk.blocking:
        return Decision.deny(message, f"command.{risk.category}", command=command)

    # A non-owner should never reach a confirmation prompt - there is nobody
    # authorised to answer it, so anything short of clearly safe is refused.
    if not ctx.is_owner:
        return Decision.deny(
            f"Blocked by CowAgent security policy: {risk.reason}.\n"
            f"This request came from {ctx.describe()}, who cannot authorise it.",
            f"command.{risk.category}",
            command=command,
        )

    return Decision.confirm(message, f"command.{risk.category}", command=command)


def _check_url_scheme(tool_name: str, args: dict, ctx: SecurityContext) -> Decision:
    """Stop file:// and other local schemes being used to read the disk."""
    if ctx.is_privileged:
        return Decision.allow()

    for key in ("url", "uri", "link", "address"):
        value = args.get(key)
        if not isinstance(value, str):
            continue
        lowered = value.strip().lower()
        if lowered.startswith(("file://", "chrome://", "about:", "data:text/html")):
            return Decision.deny(
                "Error: Access denied by CowAgent security policy. Local-file and "
                "browser-internal URLs cannot be opened on behalf of a non-owner "
                f"({ctx.describe()}).",
                "url.local_scheme",
                url=value,
            )
    return Decision.allow()


def describe_active_policy(ctx: Optional[SecurityContext] = None) -> str:
    """One-line summary of the policy in force, for logs and diagnostics."""
    ctx = ctx or current_security_context()
    if ctx.trust >= TrustLevel.OWNER:
        return f"owner ({ctx.describe()}): full access"
    if ctx.trust >= TrustLevel.TRUSTED:
        return f"trusted ({ctx.describe()}): shell allowed, owner-only tools blocked"
    allowed = ", ".join(sorted(_guest_tool_allowlist()))
    return f"guest ({ctx.describe()}): confined to workspace; tools = {allowed}"
