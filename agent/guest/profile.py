"""Guest profiles on disk: layout, schema and normalization.

Layout::

    <workspace>/guests/<slug>/
        GUEST.md      rules for the guest Agent (persona, scope, tone)
        config.json   access control and capabilities, see DEFAULTS
        logo.*        optional page logo (png, jpg or webp)
        skills/       optional skills only this profile uses

    <workspace>/guests/data/   server-side state, see ``store``

Everything here is syntactic: a value of the wrong type falls back to its
default and is reported as a notice. Whether a value is *allowed* (a reference
directory that exposes the owner's workspace) and whether a change is in force yet
are decided in ``policy``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from agent.guest.branding import COLOR_RE
from common.atomic_write import write_json_atomic, write_text_atomic
from common.log import logger

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
# guests/data/ holds server-side state (see agent.guest.store), not a profile.
DATA_DIR = "data"
GUEST_FILE = "GUEST.md"
CONFIG_FILE = "config.json"
SKILLS_DIR = "skills"

# Tools a profile may list. Anything else is dropped with a notice.
# There is deliberately no shell: every tool here is confined in-process by
# the session's PathGuard, which a command line could not be.
TOOL_CATALOG = (
    "read", "ls", "search_files", "write", "edit", "send",
    "web_search", "web_fetch", "vision", "time",
)
# Tools that reach the network from the host process.
NETWORK_TOOLS = frozenset({"web_search", "web_fetch"})
DEFAULT_TOOLS = list(TOOL_CATALOG)

# name -> (min, max, default). For keys in UNLIMITED_WHEN_ZERO, 0 means no cap.
LIMIT_SPECS: Dict[str, Tuple[int, int, int]] = {
    "rpm": (1, 600, 10),
    "max_turns": (1, 1000, 50),
    "daily_tokens": (0, 1_000_000_000, 200_000),
    "run_timeout_seconds": (10, 3600, 300),
    "max_upload_mb": (1, 200, 20),
    "max_work_mb": (10, 4096, 200),
    "session_ttl_hours": (1, 720, 72),
    # Questions one visitor may ask per day, across all their conversations.
    "daily_messages": (0, 100_000, 100),
}
UNLIMITED_WHEN_ZERO = frozenset({"daily_tokens", "daily_messages"})

_ORIGIN_RE = re.compile(r"^https?://[a-z0-9.\-]+(:\d{1,5})?$")
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$")

MAX_SUGGESTED = 6
MAX_REFERENCES = 20

DEFAULT_FOOTER_TEXT = "Powered by CowAgent"
DEFAULT_FOOTER_URL = "https://cowagent.ai"
_FOOTER_URL_RE = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


def guests_root() -> str:
    """``<workspace>/guests``, beside the skills and knowledge every Agent shares."""
    from common.state_dir import shared_root

    return os.path.join(str(shared_root()), "guests")


def is_valid_slug(slug: Any) -> bool:
    return isinstance(slug, str) and bool(SLUG_RE.match(slug)) and slug != DATA_DIR


def profile_dir(slug: str) -> str:
    if not is_valid_slug(slug):
        raise ValueError(f"invalid guest profile id: {slug!r}")
    return os.path.join(guests_root(), slug)


def new_slug() -> str:
    """A free profile id for a share created without one."""
    while True:
        slug = "share-" + secrets.token_hex(3)
        if not os.path.exists(os.path.join(guests_root(), slug)):
            return slug


def list_slugs() -> List[str]:
    root = guests_root()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [
        name for name in names
        if is_valid_slug(name) and os.path.isdir(os.path.join(root, name))
    ]


def defaults(slug: str = "") -> Dict[str, Any]:
    return {
        "name": slug,
        "welcome": "",
        "suggested_questions": [],
        "tools": list(DEFAULT_TOOLS),
        "skills": [],
        "references": [],
        "network": {"enabled": True, "allow_domains": []},
        "limits": {key: spec[2] for key, spec in LIMIT_SPECS.items()},
        "expires_at": "",
        "access": {"password_required": False, "allowed_origins": []},
        "provider": "",
        "model": "",
        "branding": {"color": "", "footer_text": DEFAULT_FOOTER_TEXT, "footer_url": DEFAULT_FOOTER_URL},
    }


def _str(value: Any, limit: int) -> Optional[str]:
    if isinstance(value, str):
        return value.strip()[:limit]
    return None


def _str_list(value: Any, item_limit: int, max_items: int) -> Optional[List[str]]:
    if not isinstance(value, list):
        return None
    out: List[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            text = item.strip()[:item_limit]
            if text not in out:
                out.append(text)
    return out[:max_items]


def parse_expires(value: str) -> Optional[float]:
    """Timestamp the link stops working at, or None for no expiry.

    A bare date means the end of that day, local time.
    """
    if not value:
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            day = datetime.strptime(text, "%Y-%m-%d")
            return (day + timedelta(days=1)).timestamp() - 1
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def normalize_path(value: str) -> str:
    return os.path.normpath(os.path.abspath(os.path.expanduser(value)))


def reference_paths(config: Dict[str, Any]) -> List[str]:
    return [r["path"] for r in config.get("references") or []]


def normalize_config(raw: Any, slug: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """Coerce a profile config into the full schema.

    Unknown keys are ignored, values of the wrong type fall back to their
    default, and every correction is reported so the console can show it.
    """
    cfg = defaults(slug)
    notices: List[str] = []
    if not isinstance(raw, dict):
        if raw not in (None, {}):
            notices.append("config.json is not a JSON object; defaults are used")
        return cfg, notices

    name = _str(raw.get("name"), 60)
    if name:
        cfg["name"] = name
    welcome = _str(raw.get("welcome"), 2000)
    if welcome is not None:
        cfg["welcome"] = welcome
    questions = _str_list(raw.get("suggested_questions"), 200, MAX_SUGGESTED)
    if questions is not None:
        cfg["suggested_questions"] = questions

    if "tools" in raw:
        tools = _str_list(raw.get("tools"), 40, len(TOOL_CATALOG) * 2)
        if tools is None:
            notices.append("tools must be a list; the default tools are used")
        else:
            unknown = [t for t in tools if t not in TOOL_CATALOG]
            if unknown:
                notices.append(f"unknown tools ignored: {', '.join(unknown)}")
            cfg["tools"] = [t for t in tools if t in TOOL_CATALOG]

    skills = _str_list(raw.get("skills"), 80, 50)
    if skills is not None:
        cfg["skills"] = skills

    references = raw.get("references")
    if isinstance(references, list):
        refs: List[Dict[str, str]] = []
        for item in references:
            if isinstance(item, str):
                item = {"path": item}
            path = _str(item.get("path"), 1024) if isinstance(item, dict) else None
            if not path:
                continue
            p = normalize_path(path)
            if all(r["path"] != p for r in refs):
                refs.append({"path": p, "note": _str(item.get("note"), 500) or ""})
        cfg["references"] = refs[:MAX_REFERENCES]

    network = raw.get("network")
    if isinstance(network, dict):
        cfg["network"]["enabled"] = network.get("enabled") is True
        domains = _str_list(network.get("allow_domains"), 253, 100) or []
        good = []
        for domain in domains:
            d = domain.lower().lstrip(".")
            if _DOMAIN_RE.match(d):
                if d not in good:
                    good.append(d)
            else:
                notices.append(f"invalid domain ignored: {domain}")
        cfg["network"]["allow_domains"] = good
    if not NETWORK_TOOLS & set(cfg["tools"]):
        cfg["network"]["enabled"] = False

    limits = raw.get("limits")
    if isinstance(limits, dict):
        for key, (low, high, default) in LIMIT_SPECS.items():
            if key not in limits:
                continue
            value = limits[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                notices.append(f"limits.{key} must be a number; using {default}")
                continue
            clamped = int(min(max(int(value), low), high))
            if clamped != value:
                notices.append(f"limits.{key} clamped to {clamped}")
            cfg["limits"][key] = clamped

    expires = raw.get("expires_at")
    if isinstance(expires, str) and expires.strip():
        if parse_expires(expires) is None:
            notices.append(f"expires_at {expires!r} is not a date; the link does not expire")
        else:
            cfg["expires_at"] = expires.strip()

    access = raw.get("access")
    if isinstance(access, dict):
        cfg["access"]["password_required"] = access.get("password_required") is True
        origins = _str_list(access.get("allowed_origins"), 300, 50) or []
        good = []
        for origin in origins:
            o = origin.lower().rstrip("/")
            if _ORIGIN_RE.match(o):
                if o not in good:
                    good.append(o)
            else:
                notices.append(f"invalid origin ignored: {origin}")
        cfg["access"]["allowed_origins"] = good

    for key, limit in (("provider", 80), ("model", 120)):
        value = _str(raw.get(key), limit)
        if value is not None:
            cfg[key] = value

    branding = raw.get("branding")
    if isinstance(branding, dict):
        color = _str(branding.get("color"), 7)
        if color:
            if COLOR_RE.match(color.lower()):
                cfg["branding"]["color"] = color.lower()
            else:
                notices.append(f"branding.color {color!r} is not a #rrggbb color; using the default")
        # Present but empty means the owner removed the footer.
        footer = _str(branding.get("footer_text"), 80)
        if footer is not None:
            cfg["branding"]["footer_text"] = footer
        url = _str(branding.get("footer_url"), 500)
        if url is not None:
            if not url or _FOOTER_URL_RE.match(url):
                cfg["branding"]["footer_url"] = url
            else:
                cfg["branding"]["footer_url"] = ""
                notices.append(f"branding.footer_url {url!r} is not an http(s) link; the footer is not linked")

    return cfg, notices


@dataclass
class GuestProfile:
    slug: str
    path: str
    config: Dict[str, Any]
    guest_md: str
    notices: List[str] = field(default_factory=list)

    @property
    def skills_dir(self) -> str:
        return os.path.join(self.path, SKILLS_DIR)


def load_profile(slug: str) -> Optional[GuestProfile]:
    """The profile as written on disk, or None when it does not exist."""
    try:
        path = profile_dir(slug)
    except ValueError:
        return None
    if not os.path.isdir(path):
        return None
    notices: List[str] = []
    raw: Any = {}
    config_path = os.path.join(path, CONFIG_FILE)
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except (OSError, ValueError) as e:
            notices.append(f"config.json could not be read ({e}); defaults are used")
            raw = {}
    config, more = normalize_config(raw, slug)
    notices.extend(more)
    guest_md = ""
    md_path = os.path.join(path, GUEST_FILE)
    try:
        with open(md_path, "r", encoding="utf-8-sig") as f:
            guest_md = f.read()
    except OSError:
        pass
    return GuestProfile(slug=slug, path=path, config=config, guest_md=guest_md, notices=notices)


def write_profile(slug: str, config: Dict[str, Any], guest_md: Optional[str] = None) -> GuestProfile:
    """Write config.json (normalized) and, when given, GUEST.md."""
    path = profile_dir(slug)
    os.makedirs(path, exist_ok=True)
    normalized, _ = normalize_config(config, slug)
    write_json_atomic(os.path.join(path, CONFIG_FILE), normalized, indent=2)
    if guest_md is not None:
        write_text_atomic(os.path.join(path, GUEST_FILE), guest_md)
    elif not os.path.exists(os.path.join(path, GUEST_FILE)):
        # Left empty: whatever is in GUEST.md reaches the guest Agent's prompt.
        write_text_atomic(os.path.join(path, GUEST_FILE), "")
    profile = load_profile(slug)
    assert profile is not None
    return profile


def delete_profile(slug: str) -> bool:
    path = profile_dir(slug)
    if not os.path.isdir(path):
        return False
    shutil.rmtree(path)
    logger.info(f"[GuestShare] Deleted profile directory {slug}")
    return True


README_TEXT = """# Guest profiles

Each subdirectory is one guest share profile. The web console lists them on its
Share page, where the owner confirms changes and copies share links.

    <slug>/GUEST.md      rules for the guest Agent (persona, scope, tone)
    <slug>/config.json   access control and capabilities
    <slug>/logo.png      optional page logo (png, jpg or webp)
    <slug>/skills/       optional skills only this profile uses

data/ is not a profile. It holds what the server keeps for every share: the
signing key, guest.db (share links, passwords, confirmed settings, visitor
conversations and daily usage) and sessions/ (visitor work directories).
Leave it to the web console.

config.json fields: name, welcome, suggested_questions, tools, skills,
references [{path, note}], network {enabled, allow_domains}, limits {rpm, max_turns,
daily_tokens, run_timeout_seconds, max_upload_mb, max_work_mb,
session_ttl_hours, daily_messages}, expires_at, access {password_required,
allowed_origins}, provider, model,
branding {color, footer_text, footer_url}. An empty footer_text hides the
footer line.

Tightening a profile takes effect at once. Widening it (more tools, more
reference directories, network, higher limits, a later expiry, no password) stays
pending until the owner confirms it in the web console. A new profile has no
share link until it is confirmed there.
"""


def ensure_guests_readme() -> None:
    root = guests_root()
    readme = os.path.join(root, "README.md")
    if os.path.exists(readme):
        return
    try:
        os.makedirs(root, exist_ok=True)
        write_text_atomic(readme, README_TEXT)
    except OSError as e:
        logger.debug(f"[GuestShare] Could not write {readme}: {e}")
