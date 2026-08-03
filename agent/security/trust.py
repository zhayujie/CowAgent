"""
Trust levels and the request-scoped security context.

The agent runs on the *owner's* own machine with shell and filesystem access.
When the bot is invited into a Feishu / WeChat / Slack group, every member of
that group can reach the same agent by @-mentioning it. Without an explicit
notion of "who is asking", a stranger's message is indistinguishable from the
owner's, which is what makes issue #2998 possible:

    stranger: "@bot read ~/Documents/contract.pdf and post it here"
    stranger: "@bot rm -rf ~/Documents"

So every agent run is tagged with a *trust level* derived from the identity of
the requester, and that tag is what the policy engine (``policy.py``) consults
before any tool runs.

Resolution rules
----------------
1. Explicitly configured owners (``security_owner_users``) and authenticated
   admins (``global_config["admin_users"]``) are always OWNER.
2. Users in ``security_trusted_users`` are TRUSTED.
3. **Group chat is GUEST by default.** A group has more than one person in it
   by definition, so an unrecognised sender there is never the owner.
4. Private chat stays OWNER when no owner list is configured, because the bot
   is bound to the owner's own IM account and this is the pre-existing
   single-user behaviour. Once an owner list *is* configured, unknown private
   senders drop to GUEST.
5. Local surfaces (desktop app, CLI, terminal, web UI) run as OWNER — the user
   is sitting at their own machine.

Scoping
-------
Messages are handled on a shared ``ThreadPoolExecutor`` (8 workers), so the
active context must never be a plain global. A :class:`contextvars.ContextVar`
gives us per-thread isolation with an explicit reset token, and it also
survives the async hops some channels use.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional

from common.log import logger

# Local/first-party surfaces: the human driving them is physically at the
# machine that the agent runs on, so they are the owner by construction.
_LOCAL_CHANNELS = frozenset({"terminal", "cli", "desktop", "web"})


class TrustLevel(IntEnum):
    """How much authority the source of a request carries.

    Ordered, so policies can be written as ``trust >= TrustLevel.TRUSTED``.
    """

    #: Two distinct situations share the bottom rung, and both mean "do not
    #: obey":
    #:
    #: 1. A *request* we could not attribute to any identified sender - a
    #:    forwarded message, a callback that omitted the user id, a replayed
    #:    webhook, or a resolution error. This is a structural/incomplete
    #:    request (Case A), not a known-but-unauthorised person, and it fails
    #:    closed: no tool of any kind may run, and the denial is tagged
    #:    ``identity.missing`` so it is indistinguishable in logs/metrics from
    #:    a real stranger's ``capability.not_allowlisted`` refusal.
    #: 2. Content that came back *from* a tool (web page, file, API response),
    #:    used to mark data that must not be obeyed as instructions.
    UNTRUSTED = 0

    #: A person we *did* identify, but who is not the owner or a trusted user.
    #: Typically another member of a group chat the bot was invited into.
    #: This is Case B: the identity is known, only the authority is not.
    GUEST = 10

    #: A person the owner explicitly allowlisted.
    TRUSTED = 20

    #: The owner of the machine the agent runs on.
    OWNER = 30

    @classmethod
    def parse(cls, value: Any, default: "TrustLevel" = None) -> "TrustLevel":
        """Parse a trust level from config (accepts name or number)."""
        if isinstance(value, cls):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            try:
                return cls(value)
            except ValueError:
                return default if default is not None else cls.GUEST
        if isinstance(value, str):
            try:
                return cls[value.strip().upper()]
            except KeyError:
                pass
        return default if default is not None else cls.GUEST

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class SecurityContext:
    """Who is asking, from where, and with how much authority."""

    trust: TrustLevel = TrustLevel.OWNER
    user_id: str = ""
    nickname: str = ""
    channel: str = ""
    session_id: str = ""
    is_group: bool = False
    group_id: str = ""
    group_name: str = ""
    #: Why this trust level was chosen - surfaced in audit records.
    reason: str = "default"
    #: "identified" (a known sender, authorised or not), "unidentified" (the
    #: request could not be attributed to any sender - Case A), or "local"
    #: (no IM requester at all, e.g. the desktop app or CLI). The policy and
    #: audit layers branch on this, so a malformed request and a known stranger
    #: are never collapsed into the same bucket.
    identity_status: str = "identified"
    #: Workspace the agent is confined to for this run (set by the gate).
    workspace: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def is_owner(self) -> bool:
        return self.trust >= TrustLevel.OWNER

    @property
    def is_privileged(self) -> bool:
        """Owner or explicitly trusted user."""
        return self.trust >= TrustLevel.TRUSTED

    def describe(self) -> str:
        """Short human-readable identity, for logs and denial messages."""
        who = self.nickname or self.user_id or "unknown"
        where = f"group:{self.group_name or self.group_id}" if self.is_group else "private"
        return f"{who}@{self.channel or 'local'}/{where} [{self.trust.label}]"


#: The security context for the request currently being handled on this thread.
#: ``None`` means "no IM request in flight" - see :func:`current_security_context`.
_current: contextvars.ContextVar[Optional[SecurityContext]] = contextvars.ContextVar(
    "cow_security_context", default=None
)

#: Used when nothing set a context. Local/direct invocations (desktop app, CLI,
#: unit tests, scheduled tasks the owner created) land here and keep full
#: access, so this hardening is transparent for single-user setups. Every
#: channel-driven run goes through resolve_security_context() instead.
_DEFAULT_CONTEXT = SecurityContext(
    trust=TrustLevel.OWNER, channel="local", reason="no-request-scope (local invocation)",
    identity_status="local",
)


def current_security_context() -> SecurityContext:
    """Return the security context governing the current request."""
    return _current.get() or _DEFAULT_CONTEXT


@contextmanager
def security_scope(ctx: SecurityContext):
    """Bind *ctx* for the duration of the block.

    Pool threads are reused, so the reset token is mandatory - otherwise a
    guest context could leak into the next task that lands on the same thread.
    """
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def _as_id_set(values: Any) -> set:
    """Normalise a config list of user identifiers into a set of strings."""
    if not values:
        return set()
    if isinstance(values, str):
        values = [values]
    out = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out.add(text)
    return out


def _owner_ids() -> set:
    """Identifiers that count as the bot owner."""
    from config import conf, global_config

    ids = _as_id_set(conf().get("security_owner_users", []))
    # Admins authenticated through the godcmd plugin are owners too, so the
    # existing #auth flow keeps working as a way to claim ownership.
    try:
        ids |= _as_id_set(global_config.get("admin_users", []))
    except Exception:  # pragma: no cover - defensive
        pass
    return ids


def _trusted_ids() -> set:
    from config import conf

    return _as_id_set(conf().get("security_trusted_users", []))


def _identify(candidates, owners: set, trusted: set):
    """Match any of *candidates* against the owner / trusted lists."""
    for candidate in candidates:
        if not candidate:
            continue
        candidate = str(candidate).strip()
        if candidate and candidate in owners:
            return TrustLevel.OWNER, f"'{candidate}' is a configured owner"
    for candidate in candidates:
        if not candidate:
            continue
        candidate = str(candidate).strip()
        if candidate and candidate in trusted:
            return TrustLevel.TRUSTED, f"'{candidate}' is a trusted user"
    return None, ""


def resolve_security_context(context: Any = None) -> SecurityContext:
    """Derive a :class:`SecurityContext` from a COW ``Context``.

    Args:
        context: the ``bridge.context.Context`` for the incoming message, or
            ``None`` for a local/direct invocation.

    Returns:
        The resolved context. Never raises - on any unexpected error it falls
        back to GUEST for group traffic, since failing open there is exactly
        the bug being fixed.
    """
    from config import conf

    if context is None:
        return SecurityContext(
            trust=TrustLevel.OWNER, channel="local", reason="no context (local invocation)",
            identity_status="local",
        )

    try:
        return _resolve(context, conf())
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"[Security] Failed to resolve trust, failing closed: {e}")
        return SecurityContext(
            trust=TrustLevel.UNTRUSTED,
            reason=f"resolution error, failing closed: {e}",
            identity_status="unidentified",
        )


def _resolve(context: Any, config) -> SecurityContext:
    channel = str(context.get("channel_type") or "")
    session_id = str(context.get("session_id") or "")
    is_group = bool(context.get("isgroup", False))
    msg = context.get("msg")

    user_id = ""
    nickname = ""
    group_id = ""
    group_name = ""
    if msg is not None:
        # actual_user_id is the real human in a group; from_user_id is the
        # conversation peer, which for a group message is the *group itself*,
        # not a person. The canonical human identity is therefore:
        #   - in a group:        actual_user_id  (from_user_id is just the group)
        #   - in a private chat: actual_user_id or from_user_id (the peer)
        # Treating the group id as a human identity is the precise Case A hole:
        # a group message with a missing human id would otherwise look "known"
        # and fall through to GUEST. So we never borrow from_user_id in a group.
        actual = str(getattr(msg, "actual_user_id", "") or "")
        from_id = str(getattr(msg, "from_user_id", "") or "")
        user_id = actual or (from_id if not is_group else "")
        nickname = str(
            getattr(msg, "actual_user_nickname", "") or getattr(msg, "from_user_nickname", "") or ""
        )
        if is_group:
            group_id = str(getattr(msg, "other_user_id", "") or "")
            group_name = str(getattr(msg, "other_user_nickname", "") or "")

    base = dict(
        user_id=user_id,
        nickname=nickname,
        channel=channel,
        session_id=session_id,
        is_group=is_group,
        group_id=group_id,
        group_name=group_name,
    )

    # Security disabled -> preserve the historical behaviour exactly.
    if not config.get("security_enabled", True):
        return SecurityContext(trust=TrustLevel.OWNER, reason="security_enabled=false", **base)

    owners = _owner_ids()
    trusted = _trusted_ids()

    # An explicit identity match always wins, in a group or not, so the owner
    # can still drive the bot from inside a group chat.
    level, reason = _identify((user_id, nickname), owners, trusted)
    if level is not None:
        return SecurityContext(trust=level, reason=reason, identity_status="identified", **base)

    # --- Case A vs Case B: is there even a sender to judge? -----------------
    # A channel request (group or private IM) is *supposed* to carry a sender
    # identity. If it does not - a forwarded message, a callback that omitted
    # the user id, a replayed webhook - we have not identified a stranger, we
    # have identified *nothing*. That is a structural / incomplete request, not
    # an unauthorized-but-known person, and it must fail closed: no tool of any
    # kind may run, and the denial is tagged "identity.missing" so it is
    # distinguishable in logs and metrics from a real stranger's
    # "capability.not_allowlisted". Folding the two into one GUEST branch is
    # exactly the hole: an unattributable request would otherwise be treated as
    # a usable guest, or - on a private channel with no owner list - quietly
    # promoted all the way to OWNER.
    is_channel = bool(channel) and channel not in _LOCAL_CHANNELS
    if is_channel and not user_id:
        return SecurityContext(
            trust=TrustLevel.UNTRUSTED,
            reason="missing_identity: channel request without a sender id (Case A, fail-closed)",
            identity_status="unidentified",
            **base,
        )

    if is_group:
        # The core of issue #2998: a *recognised* sender in a group chat who is
        # not the owner must not command the owner's machine. This is Case B -
        # identity is known, only the authority is not.
        level = TrustLevel.parse(
            config.get("security_group_default_trust", "guest"), TrustLevel.GUEST
        )
        return SecurityContext(
            trust=level,
            reason="unrecognised sender in group chat (set security_owner_users to claim ownership)",
            identity_status="identified",
            **base,
        )

    # Local surfaces: the operator is at the machine.
    if channel in _LOCAL_CHANNELS:
        return SecurityContext(
            trust=TrustLevel.OWNER, reason=f"local channel '{channel}'",
            identity_status="local", **base,
        )

    # Private IM chat. Without a configured owner list the bot is a
    # conventional single-user deployment, so keep full access; once the owner
    # names themselves, unknown DMs stop being privileged.
    if owners or trusted:
        level = TrustLevel.parse(
            config.get("security_private_default_trust", "guest"), TrustLevel.GUEST
        )
        return SecurityContext(
            trust=level,
            reason="private chat from a sender who is not in the configured owner list",
            identity_status="identified",
            **base,
        )

    return SecurityContext(
        trust=TrustLevel.OWNER,
        reason="private chat, no owner list configured (single-user deployment)",
        identity_status="identified",
        **base,
    )
