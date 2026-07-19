import os

from common.utils import expand_path
from config import conf


def get_agent_tmp_dir(
    channel_type: str = "",
    conversation_ids=(),
    agent_id: str = None,
) -> str:
    """Return the tmp directory owned by the routed Agent workspace.

    Falling back to ``agent_workspace`` preserves startup and single-Agent
    callers that run before the registry is available.
    """
    try:
        from agent.registry import get_agent_registry
        from agent.routing import get_agent_router

        registry = get_agent_registry()
        resolved_agent_id = get_agent_router(registry).resolve(
            channel_type=channel_type,
            conversation_ids=conversation_ids,
            explicit_agent_id=agent_id,
        )
        ws_root = registry.get(resolved_agent_id).workspace
    except Exception:
        ws_root = expand_path(conf().get("agent_workspace", "~/cow"))
    tmp_dir = os.path.join(ws_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


class TmpDir(object):
    """Temporary directory for transient artifacts (e.g. synthesized voice).

    Resolves to ``<agent_workspace>/tmp`` (default ``~/cow/tmp``) so temp files
    land inside the agent workspace instead of a CWD-relative ``./tmp``, which
    is unreliable for the packaged desktop app where CWD is undefined.
    """

    def __init__(self, channel_type="", conversation_ids=(), agent_id=None):
        self.tmpFilePath = get_agent_tmp_dir(
            channel_type=channel_type,
            conversation_ids=conversation_ids,
            agent_id=agent_id,
        )

    def path(self):
        return str(self.tmpFilePath) + "/"
