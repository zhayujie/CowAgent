"""Absolute paths saved before an iOS app update.

iOS gives an app's data a container with a new id whenever the app is updated
or reinstalled, and moves the data along. A path stored earlier (an artifact,
a file link in a past message, a path the agent noted down) still names the old
container, while the file sits at the same place in the new one.
"""

import functools
import os
import re

_MARK = "/Containers/Data/Application/"
_UUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
_CONTAINER = re.compile(r"^(?P<root>.*" + _MARK + _UUID + r")(?P<rest>/.*)?$")


@functools.lru_cache(maxsize=1)
def _current_container() -> str:
    """The data container this process runs in; empty outside one."""
    match = _CONTAINER.match(os.path.realpath(os.path.expanduser("~")))
    return match.group("root") if match else ""


def rebase_moved_path(path: str) -> str:
    """The same place in the current container when ``path`` names an older one
    that is gone; any other path comes back unchanged."""
    if not path or _MARK not in path:
        return path
    match = _CONTAINER.match(path)
    current = _current_container()
    if not match or not current or os.path.exists(match.group("root")):
        return path
    return current + (match.group("rest") or "")
