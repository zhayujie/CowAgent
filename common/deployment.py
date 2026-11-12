"""How this install is deployed, read from COW_DEPLOYMENT.

- ``source``: a checkout its user runs and updates with git (the default).
- ``desktop``: the packaged desktop app, which owns the backend's port,
  password and updates.
- ``docker``: a container its user runs and updates with docker compose.
- ``managed``: updated by whoever runs it, never by itself.

COW_DESKTOP=1 and COW_DOCKER=1 are the older spellings of desktop and docker
and still count.
"""

import os

DEPLOYMENTS = ("source", "desktop", "docker", "managed")


def deployment() -> str:
    value = (os.environ.get("COW_DEPLOYMENT") or "").strip().lower()
    if value in DEPLOYMENTS:
        return value
    if os.environ.get("COW_DESKTOP") == "1":
        return "desktop"
    if os.environ.get("COW_DOCKER") == "1":
        return "docker"
    return "source"


def is_desktop() -> bool:
    return deployment() == "desktop"


def is_managed() -> bool:
    return deployment() == "managed"


def manage_url() -> str:
    url = (os.environ.get("COW_MANAGE_URL") or "").strip()
    return url if url.startswith(("https://", "http://")) else ""
