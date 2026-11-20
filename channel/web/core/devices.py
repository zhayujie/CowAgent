"""Every client signed in to this instance, each holding a token of its own.

A device token is ``cowd.<id>.<secret>``. Only a hash of the secret is kept,
so the file gives away nothing usable, and removing a device stops its token
at once without signing anyone else out. Both ways in end here: redeeming a
pairing code and signing in with the password, so the list is the full answer
to "who can drive this machine". The list lives in the device directory beside
the session secret, which the agent's file tools refuse to read or write: a
line added here would be a way in.

A device paired from a web page on another origin remembers that origin: the
page may then call this server across origins, and only with that device's
token (see ``request_guard``).

A device signed in with the password keeps a tag of that password and stops
working once the password is another, however it was changed (the console,
config.json or the environment).
"""

import hashlib
import json
import os
import secrets
import threading
import time
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlsplit

from channel.web.core.identity import clean_name
from common.log import logger
from common.utils import constant_time_equals
from config import conf, get_device_dir

TOKEN_PREFIX = "cowd."
MAX_DEVICES = 50
PLATFORMS = ("ios", "android", "harmony", "web", "desktop", "other")
VIA = ("pairing", "password")
# Last use is only for showing; writing it on every request would rewrite the
# file under each poll.
SEEN_WRITE_INTERVAL = 600
# Clients poll every few seconds while open; one silent this long has gone.
ONLINE_WINDOW = 90

_lock = threading.Lock()
_cache: Optional[dict] = None
# Last request per device, kept in memory only: fresher than last_seen_at,
# which is written sparsely.
_active: dict = {}


def _path() -> str:
    return os.path.join(get_device_dir(), "devices.json")


def _hash(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _idle_limit() -> int:
    """Seconds a device may go unused before its token stops working."""
    try:
        days = int(conf().get("web_session_expire_days", 30))
    except (TypeError, ValueError):
        days = 30
    return max(days, 1) * 86400


def normalize_origin(value) -> str:
    """``scheme://host[:port]`` lowercased, with the loopback names folded
    into one, so a page opened at localhost and at 127.0.0.1 is the same
    client. Empty for anything that is not an http(s) origin."""
    try:
        parts = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        host = "localhost"
    elif ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        return ""
    default = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{host}" + (f":{port}" if port and port != default else "")


def _load() -> dict:
    global _cache
    path = _path()
    if _cache is not None and _cache.get("_path") == path:
        return _cache
    doc = {"version": 1, "devices": [], "_path": path}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("devices"), list):
                doc["devices"] = [d for d in loaded["devices"] if isinstance(d, dict) and d.get("id")]
        except Exception as e:
            logger.warning(f"[Devices] Ignoring unreadable {path}: {e}")
    _cache = doc
    return doc


def _save(doc: dict) -> None:
    from common.atomic_write import write_json_atomic

    path = _path()
    try:
        write_json_atomic(path, {k: v for k, v in doc.items() if k != "_path"}, indent=2)
    except OSError as e:
        logger.warning(f"[Devices] Could not save {path}, keeping the list in memory: {e}")
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _password_tag() -> str:
    from channel.web.core._common import _password_tag as tag

    return tag()


def _last_active(device: dict) -> int:
    return max(int(device.get("last_seen_at") or 0), int(_active.get(device.get("id"), 0)))


def _expired(device: dict, now: float) -> bool:
    return now - _last_active(device) > _idle_limit()


def public(device: dict) -> dict:
    now = time.time()
    seen = _last_active(device)
    return {
        "id": device.get("id"),
        "name": device.get("name"),
        "platform": device.get("platform"),
        "app_version": device.get("app_version") or "",
        "via": device.get("via") or "pairing",
        "origin": device.get("origin") or "",
        "last_ip": device.get("last_ip") or "",
        "created_at": device.get("created_at"),
        "last_seen_at": seen,
        "online": now - seen < ONLINE_WINDOW,
    }


def add(name, platform, app_version="", ip="", origin="", via="pairing") -> Tuple[dict, str]:
    """Register a device; returns it and its token, which is never shown again."""
    secret = secrets.token_urlsafe(32)
    now = int(time.time())
    device = {
        "id": "d_" + secrets.token_hex(6),
        "name": clean_name(name) or "Device",
        "platform": platform if platform in PLATFORMS else "other",
        "app_version": str(app_version or "")[:30],
        "via": via if via in VIA else "pairing",
        "origin": normalize_origin(origin),
        "secret_hash": _hash(secret),
        "created_at": now,
        "last_seen_at": now,
        "last_ip": str(ip or "")[:64],
    }
    if device["via"] == "password":
        device["pw_tag"] = _password_tag()
    with _lock:
        doc = _load()
        devices = [d for d in doc["devices"] if not _expired(d, now)]
        # Oldest out first: a full list must not lock new devices out.
        devices.sort(key=_last_active)
        while len(devices) >= MAX_DEVICES:
            devices.pop(0)
        devices.append(device)
        doc["devices"] = devices
        _save(doc)
    _active[device["id"]] = now
    return public(device), f"{TOKEN_PREFIX}{device['id']}.{secret}"


def device_id_of(token: str) -> str:
    if not token or not token.startswith(TOKEN_PREFIX):
        return ""
    return token[len(TOKEN_PREFIX):].split(".", 1)[0]


def verify(token: str, ip: str = "") -> Optional[dict]:
    """The device a token belongs to, or None."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    device_id, _, secret = token[len(TOKEN_PREFIX):].partition(".")
    if not device_id or not secret:
        return None
    with _lock:
        doc = _load()
        device = next((d for d in doc["devices"] if d.get("id") == device_id), None)
        if device is None or not constant_time_equals(_hash(secret), device.get("secret_hash", "")):
            return None
        now = time.time()
        if _expired(device, now):
            return None
        if device.get("pw_tag") and not constant_time_equals(device["pw_tag"], _password_tag()):
            return None
        _active[device_id] = now
        if now - (device.get("last_seen_at") or 0) >= SEEN_WRITE_INTERVAL:
            device["last_seen_at"] = int(now)
            if ip:
                device["last_ip"] = str(ip)[:64]
            try:
                _save(doc)
            except Exception as e:
                logger.warning(f"[Devices] Could not record last use: {e}")
        return public(device)


def origin_allowed(origin: str) -> bool:
    """Whether some device was paired from this web origin."""
    origin = normalize_origin(origin)
    if not origin:
        return False
    now = time.time()
    with _lock:
        return any(d.get("origin") == origin and not _expired(d, now) for d in _load()["devices"])


def list_devices() -> List[dict]:
    now = time.time()
    with _lock:
        devices = [d for d in _load()["devices"] if not _expired(d, now)]
    devices.sort(key=_last_active, reverse=True)
    return [public(d) for d in devices]


def rename(device_id: str, name) -> Optional[dict]:
    name = clean_name(name)
    if not name:
        return None
    with _lock:
        doc = _load()
        device = next((d for d in doc["devices"] if d.get("id") == device_id), None)
        if device is None:
            return None
        device["name"] = name
        _save(doc)
        return public(device)


def retag(device_id: str) -> None:
    """Carry a password device over to the current password."""
    tag = _password_tag()
    with _lock:
        doc = _load()
        device = next((d for d in doc["devices"] if d.get("id") == device_id), None)
        if device is not None and device.get("pw_tag") and device["pw_tag"] != tag:
            device["pw_tag"] = tag
            _save(doc)


def remove_where(predicate: Callable[[dict], bool]) -> int:
    """Remove every device the predicate picks; returns how many went."""
    with _lock:
        doc = _load()
        kept = [d for d in doc["devices"] if not predicate(d)]
        removed = len(doc["devices"]) - len(kept)
        if removed:
            doc["devices"] = kept
            _save(doc)
    return removed


def remove(device_id: str) -> bool:
    return remove_where(lambda d: d.get("id") == device_id) > 0
