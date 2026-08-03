"""
Filesystem guards: secret-material paths and workspace confinement.

Two independent checks live here.

``is_sensitive_path``
    A deny list of files that hold raw secret material - SSH/GPG private keys,
    cloud credentials, browser cookie and password stores, OS keychains, crypto
    wallets, shell history. It applies at *every* trust level, including the
    owner, because the realistic way these get read is not the owner asking but
    an injected instruction riding along inside a web page or document
    ("...also cat ~/.ssh/id_rsa and post it"). There is no legitimate reason for
    the agent to pull raw private-key bytes into an LLM context window, so the
    capability is simply removed. Set ``security_protect_sensitive_paths`` to
    false to opt out.

``is_within_root``
    Confinement: guests are restricted to the agent workspace, so a group-chat
    stranger cannot reach ``~/Documents`` at all. Both sides are symlink-resolved
    because an exact-prefix match on the unresolved path is trivially escaped by
    dropping a symlink inside the workspace.

This module deliberately subsumes ``agent/tools/utils/credentials.py`` rather
than replacing it: that guard stays as-is so the ~/.cow/.env boundary and its
regression tests keep working untouched.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

from common.utils import expand_path

#: Process-environment mirrors: reading them dumps every loaded secret.
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

#: Directories whose entire contents are secret material.
_SENSITIVE_DIRS = (
    "~/.ssh",                       # private keys, authorized_keys
    "~/.gnupg",                     # GPG private keyring
    "~/.aws",                       # AWS access keys
    "~/.azure",
    "~/.config/gcloud",             # GCP credentials
    "~/.kube",                      # cluster admin credentials
    "~/Library/Keychains",          # macOS keychain
    "~/.local/share/keyrings",      # GNOME keyring
    "~/.password-store",            # pass(1)
    "~/.ethereum/keystore",
    "~/.bitcoin/wallets",
    "~/.electrum/wallets",
)

#: Individual files holding credentials or auth tokens.
_SENSITIVE_FILES = (
    "~/.netrc",
    "~/.git-credentials",
    "~/.npmrc",
    "~/.pypirc",
    "~/.docker/config.json",
    "~/.cow/.env",                  # the agent's own API keys
    "~/.bash_history",              # frequently contains pasted tokens
    "~/.zsh_history",
    "~/.python_history",
    "~/.mysql_history",
    "~/.psql_history",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/master.passwd",
)

#: Browser profile artefacts: session cookies and saved passwords. Matched by
#: basename under a recognised browser profile directory.
_BROWSER_SECRET_FILES = frozenset(
    {
        "cookies",
        "cookies.sqlite",
        "login data",
        "login data for account",
        "logins.json",
        "key4.db",
        "key3.db",
        "web data",
        "local state",
    }
)

_BROWSER_DIR_MARKERS = (
    "/google/chrome",
    "/chromium",
    "/microsoft edge",
    "/bravesoftware",
    "/firefox",
    "/mozilla",
    "/safari",
    "/arc",
)

#: Filename patterns that are private keys wherever they live.
_KEY_FILE_RE = re.compile(
    r"(^|/)(id_(rsa|dsa|ecdsa|ed25519)|.*\.(pem|pfx|p12|keystore|jks))$"
)

DENIED_SENSITIVE = (
    "Error: Access denied by CowAgent security policy. '{path}' holds credentials or "
    "private key material ({kind}), which is never readable by the agent.\n"
    "If a task genuinely needs a secret, ask the user to store it via the env_config "
    "tool and reference it by name instead of reading the file."
)

DENIED_OUTSIDE_WORKSPACE = (
    "Error: Access denied by CowAgent security policy. This request came from {who}, "
    "who is not the owner of this machine, so file access is confined to the agent "
    "workspace ({root}).\n"
    "'{path}' is outside that workspace and will not be read, written or sent.\n"
    "If this person should have broader access, the owner must add them to "
    "security_owner_users or security_trusted_users in the config."
)


def _normalise(path: str) -> Tuple[str, str]:
    """Return (normalised, symlink-resolved) POSIX-style forms of *path*."""
    try:
        normalised = os.path.normpath(path).replace(os.sep, "/")
    except Exception:
        normalised = str(path).replace(os.sep, "/")
    try:
        resolved = os.path.realpath(path).replace(os.sep, "/")
    except OSError:
        resolved = normalised
    return normalised, resolved


def _expanded(path: str) -> str:
    try:
        return os.path.realpath(expand_path(path)).replace(os.sep, "/")
    except Exception:
        return expand_path(path).replace(os.sep, "/")


def _under(candidate: str, directory: str) -> bool:
    """True if *candidate* is *directory* itself or lives under it."""
    if not directory:
        return False
    directory = directory.rstrip("/")
    return candidate == directory or candidate.startswith(directory + "/")


def sensitive_path_kind(absolute_path: str) -> Optional[str]:
    """Describe why *absolute_path* is protected, or ``None`` if it is not.

    Checks both the plain and the symlink-resolved form, so a symlink planted
    inside an allowed directory cannot be used to reach a protected target.
    """
    if not absolute_path:
        return None

    candidates = set(_normalise(absolute_path))

    for candidate in candidates:
        if _PROC_ENVIRON_RE.match(candidate):
            return "process environment dump"

    for candidate in candidates:
        lowered = candidate.lower()

        for directory in _SENSITIVE_DIRS:
            if _under(candidate, _expanded(directory)):
                return f"protected directory {directory}"

        for file_path in _SENSITIVE_FILES:
            if candidate == _expanded(file_path):
                return f"credential file {file_path}"

        if _KEY_FILE_RE.search(lowered):
            return "private key file"

        basename = lowered.rsplit("/", 1)[-1]
        if basename in _BROWSER_SECRET_FILES and any(
            marker in lowered for marker in _BROWSER_DIR_MARKERS
        ):
            return "browser cookie/password store"

    return None


def is_sensitive_path(absolute_path: str) -> bool:
    """True if *absolute_path* points at protected secret material."""
    from config import conf

    if not conf().get("security_protect_sensitive_paths", True):
        return False
    return sensitive_path_kind(absolute_path) is not None


def is_within_root(absolute_path: str, root: str) -> bool:
    """True if *absolute_path* resolves to somewhere inside *root*.

    For a path that does not exist yet (a file about to be written) the nearest
    existing ancestor is resolved instead, so a write through a symlinked
    parent is still caught.
    """
    if not root:
        return False

    root_resolved = _expanded(root)
    normalised, resolved = _normalise(absolute_path)

    if _under(normalised, root_resolved) and _under(resolved, root_resolved):
        return True

    # Target may not exist yet - resolve the closest existing ancestor.
    probe = os.path.dirname(os.path.normpath(absolute_path))
    seen = 0
    while probe and seen < 64:
        if os.path.exists(probe):
            probe_resolved = os.path.realpath(probe).replace(os.sep, "/")
            tail = os.path.normpath(absolute_path).replace(os.sep, "/")
            return _under(probe_resolved, root_resolved) and _under(tail, root_resolved)
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
        seen += 1

    return False


def extract_paths(tool_name: str, args: dict) -> list:
    """Best-effort extraction of filesystem paths from a tool's arguments.

    Only the argument names the bundled tools actually use are inspected; an
    unknown tool contributes nothing here and is instead governed by the
    capability profile in ``policy.py``.
    """
    if not isinstance(args, dict):
        return []

    keys = (
        "file_path", "path", "filepath", "target_path", "notebook_path",
        "directory", "dir", "dir_path", "root", "source", "destination",
    )
    paths = []
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())

    # `send` accepts a local file or a URL under the same key.
    for key in ("file", "url"):
        value = args.get(key)
        if isinstance(value, str) and value.strip() and not _looks_like_url(value):
            paths.append(value.strip())

    return paths


def _looks_like_url(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value.strip()))


def resolve_against(path: str, cwd: Optional[str]) -> str:
    """Resolve *path* the way the file tools do: expand ~, then join to *cwd*."""
    expanded = expand_path(path)
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    base = cwd or os.getcwd()
    return os.path.normpath(os.path.join(base, expanded))
