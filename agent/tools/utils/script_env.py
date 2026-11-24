"""Environment variables a skill script expects from the tool that runs it."""

from typing import Dict, Optional

_HEADER_TO_ENV = {
    "X-Agent-Run-Id": "COW_AGENT_RUN_ID",
    "X-Client-Source": "COW_CLIENT_SOURCE",
    "X-Client-OS": "COW_CLIENT_OS",
    "X-Client-Version": "COW_CLIENT_VERSION",
    "X-Deployment-Id": "COW_DEPLOYMENT_ID",
}


def script_env(workspace: Optional[str]) -> Dict[str, str]:
    """Variables to add to a script's environment.

    AGENT_WORKSPACE anchors artifact outputs (e.g. image-generation) to the
    workspace regardless of the live cwd. The COW_* values carry the current
    run/source identity.
    """
    env = {}
    if workspace:
        env["AGENT_WORKSPACE"] = workspace
    try:
        from common import utils as cow_utils
        attr = {}
        cow_utils.apply_client_source(attr)
        for header, name in _HEADER_TO_ENV.items():
            if attr.get(header):
                env[name] = attr[header]
    except Exception:
        pass
    return env
