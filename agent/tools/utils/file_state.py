"""
Cross-tool record of when the agent last read each file.

The tool manager builds a fresh tool instance per call, so this state has to
live at module level to be shared between read, edit and write. Observations
are scoped to the current conversation: another conversation reading the same
file must not replace the snapshot this agent actually saw.

It powers a staleness warning: if a file changed on disk after the agent read
it, the agent is probably about to overwrite someone else's change (the user
editing by hand, a scheduled task, or a concurrent agent). We warn rather than
block - unlike a single-user coding CLI, this agent runs across channels where
legitimate outside edits are common, and hard-failing would strand the model
with no way forward.
"""

import os
import threading
from collections import OrderedDict
from typing import Optional

# Bound all conversations together so a long-running process cannot grow
# without limit.
_MAX_TRACKED = 512

_lock = threading.Lock()
_read_mtimes = OrderedDict()  # conversation + realpath -> observed mtime


def _key(path: str) -> Optional[str]:
    try:
        return os.path.realpath(path)
    except OSError:
        return None


def _observation_key(path: str) -> tuple:
    from common.runtime_identity import current_identity

    identity = current_identity()
    # Keep observations across turns of the same conversation. A fresh run id
    # must not discard a file view still present in that conversation's context.
    return identity.agent_id, identity.user_id, identity.session_id, path


def _current_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def note_read(path: str) -> None:
    """Record that the agent has just seen the current contents of *path*."""
    key = _key(path)
    if not key:
        return
    mtime = _current_mtime(key)
    if mtime is None:
        return
    observation = _observation_key(key)
    with _lock:
        _read_mtimes[observation] = mtime
        _read_mtimes.move_to_end(observation)
        while len(_read_mtimes) > _MAX_TRACKED:
            _read_mtimes.popitem(last=False)


# A write is also a point where our view of the file becomes current, so the
# next edit must not be flagged as stale.
note_write = note_read


def staleness_warning(path: str) -> Optional[str]:
    """Warn if *path* changed since the agent last read it.

    Returns None when the file is unchanged, or when the agent never read it -
    an unread file carries no expectation to violate, and warning there would
    fire on every legitimate first write.
    """
    key = _key(path)
    if not key:
        return None
    with _lock:
        seen = _read_mtimes.get(_observation_key(key))
    if seen is None:
        return None
    current = _current_mtime(key)
    if current is None or current == seen:
        return None
    return (
        f"{os.path.basename(key)} was modified after you last read it "
        "(by the user, a scheduled task, or another agent). Your change was "
        "applied on top of the older content - read the file again to confirm "
        "the result is what you intended."
    )


def reset() -> None:
    """Clear all tracked state. For tests."""
    with _lock:
        _read_mtimes.clear()
