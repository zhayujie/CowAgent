"""A guest share as it stands right now, and the owner's operations on it.

``resolve`` combines the three inputs that decide what a visitor gets:

- the profile on disk (``profile``), which anyone with write access to the
  workspace can edit, the main Agent included;
- the configuration the owner last confirmed in the console (``store``);
- what may never be enabled (``policy``).

The result is recomputed on every request, so a tightening edit to the file
reaches the very next message, and nothing that widens access is in force
until the owner confirms it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.guest import branding, policy, store
from agent.guest.profile import (
    GuestProfile,
    load_profile,
    normalize_config,
    parse_expires,
    write_profile,
)
from common.log import logger

STATUS_ACTIVE = "active"
STATUS_UNCONFIRMED = "unconfirmed"
STATUS_DISABLED = "disabled"
STATUS_EXPIRED = "expired"
STATUS_NEEDS_PASSWORD = "password_missing"


def feature_status() -> Dict[str, Any]:
    """Whether guest shares may be served at all on this instance."""
    from config import conf

    settings = conf().get("guest_share") or {}
    enabled = isinstance(settings, dict) and settings.get("enabled") is True
    password_set = bool(str(conf().get("web_password", "") or ""))
    reason = ""
    if not enabled:
        reason = "disabled"
    elif not password_set:
        # The console shares the port with the guest pages. Without a console
        # password every visitor could open the console and every management
        # API, so the guest pages stay off.
        reason = "web_password_required"
    return {"enabled": enabled, "web_password_set": password_set, "serving": not reason, "reason": reason}


@dataclass
class ShareState:
    slug: str
    profile: GuestProfile
    entry: Optional[Dict[str, Any]]
    file_config: Dict[str, Any]
    effective: Optional[Dict[str, Any]]
    status: str
    pending: List[str] = field(default_factory=list)
    notices: List[str] = field(default_factory=list)

    @property
    def share_token(self) -> str:
        return (self.entry or {}).get("share_token") or ""

    @property
    def active(self) -> bool:
        return self.status == STATUS_ACTIVE and self.effective is not None

    def session_ttl(self) -> int:
        cfg = self.effective or self.file_config
        return int((cfg.get("limits") or {}).get("session_ttl_hours") or 72) * 3600


def resolve(slug: str) -> Optional[ShareState]:
    profile = load_profile(slug)
    if profile is None:
        return None
    entry = store.get_entry(slug)
    notices = list(profile.notices)

    file_config, hard = policy.enforce_hard_rules(profile.config)
    notices.extend(hard)

    effective = None
    pending: List[str] = []
    if entry and isinstance(entry.get("confirmed"), dict):
        confirmed, _ = normalize_config(entry["confirmed"], slug)
        confirmed, _ = policy.enforce_hard_rules(confirmed)
        effective, pending = policy.meet(confirmed, file_config)

    if effective is None:
        status = STATUS_UNCONFIRMED
    elif entry.get("disabled"):
        status = STATUS_DISABLED
    elif (parse_expires(effective.get("expires_at") or "") or float("inf")) < time.time():
        status = STATUS_EXPIRED
    elif (effective.get("access") or {}).get("password_required") and not entry.get("password_hash"):
        status = STATUS_NEEDS_PASSWORD
    else:
        status = STATUS_ACTIVE

    return ShareState(
        slug=slug,
        profile=profile,
        entry=entry,
        file_config=file_config,
        effective=effective,
        status=status,
        pending=pending,
        notices=notices,
    )


def resolve_by_token(share_token: str) -> Optional[ShareState]:
    slug = store.find_by_share_token(share_token)
    if not slug:
        return None
    return resolve(slug)


# --- owner operations (console only) -----------------------------------------


def save_and_confirm(slug: str, config: Dict[str, Any], guest_md: Optional[str] = None) -> ShareState:
    """Write the profile and confirm it in one step. Only for the console,
    where the owner is authenticated: this is what makes a widening real."""
    profile = write_profile(slug, config, guest_md)
    allowed, _ = policy.enforce_hard_rules(profile.config)
    store.confirm(slug, allowed)
    logger.info(f"[GuestShare] Profile {slug} saved and confirmed from the console")
    state = resolve(slug)
    assert state is not None
    return state


def confirm_current(slug: str) -> Optional[ShareState]:
    """Accept what the profile file says now, minus anything never allowed."""
    state = resolve(slug)
    if state is None:
        return None
    store.confirm(slug, state.file_config)
    logger.info(f"[GuestShare] Profile {slug} confirmed: {state.pending or 'initial confirmation'}")
    return resolve(slug)


def describe(state: ShareState) -> Dict[str, Any]:
    """The share as the console shows it. Never includes secrets other than
    the share token, which the owner needs to build the link."""
    cfg = state.effective or state.file_config
    entry = state.entry or {}
    return {
        "slug": state.slug,
        "name": cfg.get("name") or state.slug,
        "status": state.status,
        "share_token": state.share_token if state.effective is not None else "",
        "password_set": bool(entry.get("password_hash")),
        "disabled": bool(entry.get("disabled")),
        "confirmed_at": entry.get("confirmed_at") or 0,
        "pending": state.pending,
        "notices": state.notices,
        "file_config": state.file_config,
        "effective_config": state.effective,
        "logo_version": branding.logo_version(state.profile.path),
    }
