"""
Shared credential-path guard for file tools.

The agent's API keys live in ~/.cow/.env and must only ever be reached through
the env_config tool. Every tool that can surface file contents to the model has
to apply the same check - guarding only the read tool leaves the others as
bypasses (a successful edit, for example, returns a diff containing the
surrounding lines).

Scope is deliberately narrow (the credential file and its process-environment
aliases) so this does not re-broaden the block that issue #2863 intentionally
narrowed to ~/.cow/.env. See also issue #2913 for the bypasses handled here.
"""

import os
import re

from common.utils import cow_home

# Paths whose CONTENT mirrors the process environment (and thus any secrets
# loaded from ~/.cow/.env). Reading them bypasses the env_config boundary.
# Matches /proc/self/environ, /proc/thread-self/environ and /proc/<pid>/environ.
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

DENIED_MESSAGE = (
    "Error: Access denied. API keys and credentials must be accessed "
    "through the env_config tool only."
)


def is_credential_path(absolute_path: str) -> bool:
    """Return True if *absolute_path* points at protected credential data.

    Beyond the literal ~/.cow/.env file, this also blocks two real bypass
    surfaces reported in issue #2913:
      1. /proc/<pid|self|thread-self>/environ - a second view of the
         process environment that leaks secrets loaded from ~/.cow/.env.
      2. Symlinks resolving to ~/.cow/.env; an exact abspath match keeps the
         link target and can be bypassed.
    """
    # Compare on both the normalized path and the symlink-resolved path,
    # in POSIX form so the /proc regex matches regardless of os.sep.
    candidates = set()
    try:
        candidates.add(os.path.normpath(absolute_path).replace(os.sep, "/"))
        candidates.add(os.path.realpath(absolute_path).replace(os.sep, "/"))
    except OSError:
        candidates.add(absolute_path.replace(os.sep, "/"))

    # 1. /proc environ aliases (checked on raw and symlink-resolved forms).
    for candidate in candidates:
        if _PROC_ENVIRON_RE.match(candidate):
            return True

    # 2. The credential file itself, following symlinks on both sides.
    env_real = os.path.realpath(os.path.join(cow_home(), ".env")).replace(os.sep, "/")
    return env_real in candidates
