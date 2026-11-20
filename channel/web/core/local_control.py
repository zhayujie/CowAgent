"""Lets commands run on this machine, such as ``cow pair``, reach the console.

While serving, the console keeps a file in the device directory holding the
address it answers on and a random key, readable by this user only. A command
reads the file and sends the key back. Whoever can read the file already
controls this account, config.json included, so the key grants nothing new;
nobody else can produce it. The key changes on every start.
"""

import json
import os
import secrets
from typing import Optional

from common.log import logger
from common.utils import constant_time_equals
from config import get_device_dir

FILE_NAME = "console.json"
HEADER = "HTTP_X_COW_LOCAL_KEY"

_key = ""
_host = ""


def path() -> str:
    return os.path.join(get_device_dir(), FILE_NAME)


def _connect_host(host: str) -> str:
    if host in ("", "0.0.0.0"):
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def publish(host: str, port: int, scheme: str) -> None:
    """Record where the console listens now; called on every bind."""
    global _key, _host
    if not _key:
        _key = secrets.token_urlsafe(32)
    _host = _connect_host(host)
    netloc = f"[{_host}]" if ":" in _host else _host
    payload = {"pid": os.getpid(), "url": f"{scheme}://{netloc}:{int(port)}", "key": _key}
    target = path()
    tmp = target + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except OSError as e:
        logger.debug(f"[WebChannel] Could not write {target}: {e}")


def withdraw() -> None:
    """Remove the file if it is still ours, so no command finds a stale key."""
    target = path()
    try:
        with open(target, encoding="utf-8") as f:
            if json.load(f).get("pid") != os.getpid():
                return
        os.remove(target)
    except (OSError, ValueError):
        pass


def _from_this_machine(env: dict) -> bool:
    if env.get("HTTP_X_FORWARDED_FOR") or env.get("HTTP_X_REAL_IP"):
        return False
    addr = (env.get("REMOTE_ADDR") or "").strip()
    if addr.startswith("::ffff:"):
        addr = addr[len("::ffff:"):]
    return addr == "::1" or addr.startswith("127.") or (bool(_host) and addr == _host)


def key_matches(env: Optional[dict]) -> bool:
    """Whether the request comes from this machine carrying the current key."""
    if not _key or not env:
        return False
    provided = env.get(HEADER, "") or ""
    return bool(provided) and _from_this_machine(env) and constant_time_equals(provided, _key)
