"""Default location of the Agent workspace.

``COW_DEFAULT_WORKSPACE``, else ``~/cow``. This is how the desktop shell applies
the workspace location the user picked at install time or in Settings. An
explicit ``agent_workspace`` in config.json always wins over it.

Config and credentials (``~/.cow``) deliberately have no such override.
"""

import os

from common.utils import expand_path


def default_workspace() -> str:
    return expand_path((os.environ.get("COW_DEFAULT_WORKSPACE") or "").strip() or "~/cow")
