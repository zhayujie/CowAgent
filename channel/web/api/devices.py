"""Pairing other devices with this instance, and every device signed in.

A signed-in client, or ``cow pair`` on a server without a screen, creates a
one-time code and shows it as a QR code; the new device redeems it at
/auth/pair for a token of its own, which can be revoked on its own later.
Signing in with the password issues the same kind of token, so the device list
covers every client. /.well-known/cowagent tells a client what it reached, and
which device, before it hands over any credential.
"""

import json
import re
from typing import Tuple
from urllib.parse import urlencode, urlsplit

import web

from agent.guest.access import LoginLimiter
from channel.web.api.integrations import is_loopback_host, lan_urls, public_url
from channel.web.core import devices, identity, local_control, pairing
from channel.web.core._common import (
    _client_ip, _current_device_token, _is_password_enabled, _qr_data_uri,
    _require_auth, _set_auth_cookie,
)
from channel.web.core.request_guard import cross_site_origin
from common.deployment import is_managed
from common.log import logger

PROTOCOL_VERSION = 1
PAIR_LINK = "cowagent://pair"

# Redeeming is open to anyone who can reach the server, so wrong codes are
# capped the same way wrong passwords are.
_pair_limiter = LoginLimiter()


def _json(payload: dict) -> str:
    web.header("Content-Type", "application/json; charset=utf-8")
    return json.dumps(payload, ensure_ascii=False)


def _error(message: str, reason: str) -> str:
    return _json({"status": "error", "message": message, "reason": reason})


def _version() -> str:
    try:
        from cli import __version__

        return __version__
    except Exception:
        return ""


def _instance() -> dict:
    # A managed instance is named by whoever runs it, so clients don't offer a rename.
    return {"id": identity.device_id(), "name": identity.device_name(), "version": _version(),
            "managed": is_managed()}


def _usable(url: str, origin_only: bool = False) -> str:
    """``url`` if another device could open it, else empty."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    if is_loopback_host(parts.hostname) or parts.hostname.endswith(".localhost"):
        return ""
    if origin_only:
        return f"{parts.scheme}://{parts.netloc}"
    return url.strip()


def pairing_urls(seen_at: str = "") -> list:
    """Addresses worth trying from another device, most likely first."""
    candidates = [_usable(public_url()), _usable(seen_at, origin_only=True)] + lan_urls()
    urls = []
    for url in candidates:
        url = (url or "").rstrip("/")
        if url and url not in urls:
            urls.append(url)
    return urls


def pair_link(secret: str, urls: list) -> str:
    query = [("v", str(PROTOCOL_VERSION)), ("c", secret)] + [("u", u) for u in urls]
    return f"{PAIR_LINK}?{urlencode(query)}"


def current_device_id() -> str:
    token = _current_device_token()
    if token and devices.verify(token):
        return devices.device_id_of(token)
    return ""


_BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
             ("Chrome/", "Chrome"), ("Safari/", "Safari"))
_SYSTEMS = (("iPhone", "iOS"), ("iPad", "iPadOS"), ("HarmonyOS", "HarmonyOS"),
            ("OpenHarmony", "HarmonyOS"), ("Android", "Android"), ("Mac OS X", "macOS"),
            ("Windows", "Windows"), ("CrOS", "ChromeOS"), ("Linux", "Linux"))


def describe_client(info=None) -> Tuple[str, str, str]:
    """Name, platform and version for a device signing in.

    Apps say who they are in the request; a browser is named after itself and
    its system from the User-Agent, which is only a label the owner reads.
    """
    info = info if isinstance(info, dict) else {}
    name = str(info.get("name") or "").strip()
    platform = str(info.get("platform") or "").strip()
    version = str(info.get("app_version") or "").strip()
    if name and platform:
        return name, platform, version
    ua = web.ctx.env.get("HTTP_USER_AGENT", "") or ""
    browser = next((label for key, label in _BROWSERS if key in ua), "")
    system = next((label for key, label in _SYSTEMS if key in ua), "")
    # Electron puts the app's product name in its User-Agent; other Electron
    # apps with a built-in browser are just browsers here.
    if "Electron/" in ua and "CowAgent/" in ua:
        guess = f"CowAgent Desktop · {system}" if system else "CowAgent Desktop"
        return name or guess, platform or "desktop", version
    if browser:
        guess = f"{browser} · {system}" if system else browser
        return name or guess, platform or "web", version
    product = re.match(r"[\w.-]+", ua)
    return name or (product.group(0) if product else "Device"), platform or "other", version


def issue_password_device(info=None) -> str:
    """Register the caller as a device signed in with the password; sets the
    console cookie and returns the token for clients that send it back in a
    header instead."""
    name, platform, version = describe_client(info)
    device, token = devices.add(name, platform, version, ip=_client_ip(), via="password")
    _set_auth_cookie(token)
    logger.info(f"[Devices] {device['name']} ({device['platform']}) signed in with the password")
    return token


class WellKnownHandler:
    """What this server is, before any credential: lets a client tell a
    CowAgent instance from whatever else answers at an address."""

    def GET(self):
        return _json({
            "type": "instance",
            "protocol": PROTOCOL_VERSION,
            # The id, not the name: anyone on the network can ask.
            "id": identity.device_id(),
            "version": _version(),
            "auth": {
                "required": _is_password_enabled(),
                "methods": ["password", "pairing"],
            },
        })


def _require_owner():
    """Signed in, or ``cow pair`` on this machine, which has no session."""
    if not local_control.key_matches(web.ctx.env):
        _require_auth()


class PairingHandler:
    def POST(self):
        _require_owner()
        try:
            data = json.loads(web.data() or b"{}")
        except Exception:
            data = {}
        urls = pairing_urls(str(data.get("base_url") or ""))
        if not urls:
            return _error("This instance only listens on this computer", "local_only")
        p = pairing.create()
        link = pair_link(p.secret, urls)
        logger.info(f"[Devices] Pairing code created ({len(urls)} address(es))")
        return _json({
            "status": "success",
            "pairing_id": p.id,
            "code": pairing.format_code(p.code),
            "expires_in": pairing.TTL_SECONDS,
            "urls": urls,
            "link": link,
            "qr_image": _qr_data_uri(link),
            "password_set": _is_password_enabled(),
            "instance": _instance(),
        })


class PairingStatusHandler:
    def GET(self, pairing_id):
        _require_owner()
        p = pairing.get(pairing_id)
        if p is None:
            return _json({"status": "success", "state": "expired"})
        return _json({"status": "success", "state": p.status(), "device": p.device})


class AuthPairHandler:
    """Trade a pairing code for a device token. Unauthenticated: the code is
    the credential."""

    def POST(self):
        try:
            data = json.loads(web.data() or b"{}")
        except Exception:
            return _error("Invalid request", "invalid")
        client = _client_ip()
        wait = _pair_limiter.locked_for("pair", client)
        if wait:
            return _json({"status": "error", "reason": "locked", "retry_after": wait,
                          "message": f"Too many attempts. Try again in {wait} seconds."})
        p = pairing.claim(str(data.get("code") or ""))
        if p is None:
            _pair_limiter.failed("pair", client)
            logger.warning(f"[Devices] Invalid pairing code from {client}")
            return _error("The code is wrong or has expired", "invalid_code")
        _pair_limiter.succeeded("pair", client)
        name, platform, version = describe_client(data.get("device"))
        # A page on another origin pairing here may call this server from
        # that origin from now on, with this device's token only.
        origin = cross_site_origin(web.ctx.env)
        device, token = devices.add(name, platform, version, ip=client, origin=origin)
        pairing.complete(p, device)
        logger.info(f"[Devices] Paired {device['name']} ({device['platform']}) from {client}"
                    + (f", page {device['origin']}" if device["origin"] else ""))
        return _json({"status": "success", "token": token, "device": device, "instance": _instance()})


class DevicesHandler:
    def GET(self):
        _require_auth()
        return _json({
            "status": "success",
            "devices": devices.list_devices(),
            "current": current_device_id(),
            "instance": _instance(),
            "password_set": _is_password_enabled(),
        })


class DeviceSelfHandler:
    """This device's own name, which every client shows."""

    def PATCH(self):
        _require_auth()
        try:
            data = json.loads(web.data() or b"{}")
        except Exception:
            data = {}
        from channel.web.api.integrations import save_config_values

        # Empty goes back to the computer's name.
        save_config_values({"device_name": identity.clean_name(data.get("name"))})
        logger.info(f"[Devices] This device is now called {identity.device_name()}")
        return _json({"status": "success", "instance": _instance()})


class DevicesRevokeOthersHandler:
    def POST(self):
        _require_auth()
        current = current_device_id()
        removed = devices.remove_where(lambda d: d.get("id") != current)
        logger.info(f"[Devices] Signed out {removed} other device(s)")
        return _json({"status": "success", "removed": removed})


class DeviceHandler:
    def PATCH(self, device_id):
        _require_auth()
        try:
            data = json.loads(web.data() or b"{}")
        except Exception:
            data = {}
        device = devices.rename(device_id, data.get("name"))
        if device is None:
            return _error("Device not found", "not_found")
        return _json({"status": "success", "device": device})

    def DELETE(self, device_id):
        _require_auth()
        if not devices.remove(device_id):
            return _error("Device not found", "not_found")
        logger.info(f"[Devices] Removed device {device_id}")
        return _json({"status": "success"})
