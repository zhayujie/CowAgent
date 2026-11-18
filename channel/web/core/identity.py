"""Who this device is: a stable id and a name people recognise.

The id lets a client confirm that the address it saved still leads to the
device it paired with before handing over that device's token: a LAN address
can be given to another machine, and a token sent there is a token given away.
It is random, kept in the device directory, and not a secret.

The name is the owner's to change (``device_name`` in config.json) and every
client shows the same one. Until it is set, it is the computer's own name as
the system shows it to people.
"""

import os
import re
import secrets
import socket
import subprocess
import sys
import threading
from typing import Optional

from common.deployment import is_mobile
from common.log import logger
from config import conf, get_device_dir

NAME_MAX = 60
_ID_FILE = "device_id"
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{4,80}$")
# Container runtimes name the host after the container id.
_CONTAINER_HOST_RE = re.compile(r"^[0-9a-f]{12}([0-9a-f]{52})?$")

_lock = threading.Lock()
_id: Optional[str] = None
_system_name: Optional[str] = None


def clean_name(value) -> str:
    return " ".join(str(value or "").split())[:NAME_MAX]


def device_id() -> str:
    global _id
    if _id is not None:
        return _id
    with _lock:
        if _id is not None:
            return _id
        path = os.path.join(get_device_dir(), _ID_FILE)
        value = ""
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    value = f.read().strip()
        except OSError as e:
            logger.warning(f"[Identity] Could not read {path}: {e}")
        if not _ID_RE.match(value):
            value = "dev_" + secrets.token_hex(8)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(value)
            except OSError as e:
                logger.warning(f"[Identity] Could not write {path}: {e}")
        _id = value
        return _id


def _macos_computer_name() -> str:
    try:
        out = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True,
                             text=True, timeout=2)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _linux_pretty_name() -> str:
    try:
        with open("/etc/machine-info", "r", encoding="utf-8") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == "PRETTY_HOSTNAME":
                    return value.strip().strip('"')
    except OSError:
        pass
    return ""


def system_name() -> str:
    """The computer's name as its owner sees it, or "" when it has none worth
    showing (a container, the phone's embedded kernel)."""
    global _system_name
    if _system_name is not None:
        return _system_name
    name = ""
    if not is_mobile():
        if sys.platform == "darwin":
            name = _macos_computer_name()
        elif sys.platform.startswith("linux"):
            name = _linux_pretty_name()
        if not name:
            try:
                name = socket.gethostname() or ""
            except (OSError, UnicodeError):
                name = ""
            if name.endswith(".local"):
                name = name[: -len(".local")]
            if _CONTAINER_HOST_RE.match(name):
                name = ""
    _system_name = clean_name(name)
    return _system_name


def device_name() -> str:
    return clean_name(conf().get("device_name")) or system_name() or "CowAgent"


def reset() -> None:
    global _id, _system_name
    with _lock:
        _id = None
        _system_name = None
