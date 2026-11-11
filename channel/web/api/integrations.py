"""Settings shared by the console's Integrations tab.

``web_public_url`` is the address the console shows in API examples, share
links and embed snippets, for owners reached through a domain or a public IP.
It is only displayed; the server listens and answers as before.

Without one, a console opened on this machine has nothing better to show than
``localhost``, which is no use to anyone else. When the server listens on all
interfaces (it does once a console password is set), the tab also gets this
machine's addresses on the local network, so a link can be handed to another
device on the same network.

``web_host`` is where the server listens. Changing it here moves the running
server to the new address, so no restart is needed.

Behind ``web_auth_proxy`` the proxy is the only way in: the listen address is
its to route to, and this machine's addresses reach no one, so neither is
shown or changed here. A ``web_public_url`` set in the environment wins over
config.json at every start, so it is shown but not edited either.
"""

import ipaddress
import json
import os
import re
import socket
import sys
from typing import List

import web

from common.log import logger
from channel.web.core._common import (
    _is_password_enabled,
    _read_config_file_for_write,
    _require_auth,
    _write_config_file_for_write,
)

_PUBLIC_URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+(:\d{1,5})?(/[A-Za-z0-9._~\-/]*)?$")
# Interfaces VPNs, containers and VMs create; their addresses are not on the
# network the user's other devices share.
_VIRTUAL_IFACE_RE = re.compile(r"^(utun|tun|tap|wg|zt|tailscale|docker|br-|veth|vmnet|vboxnet|bridge|llw|awdl|virbr|cni|flannel)", re.I)
# Addresses VPN and proxy tools hand out on virtual interfaces.
_VIRTUAL_NETS = (ipaddress.ip_network("198.18.0.0/15"), ipaddress.ip_network("100.64.0.0/10"))
# Where there is no interface list, these are probed to learn which local
# address the OS routes from; a UDP connect sends nothing.
_PRIVATE_PROBES = ("192.168.255.255", "10.255.255.255", "172.31.255.255")

_ALL_INTERFACES = ("0.0.0.0", "::")

_listen = {"host": "", "port": 0, "scheme": "http"}


def record_listen(host: str, port: int, scheme: str) -> None:
    """Where the server is bound right now, which config.json may not say:
    startup can fall back to loopback, and a move can fail."""
    _listen.update(host=host, port=int(port), scheme=scheme)


def _lan_rank(ip: str) -> int:
    """Home ranges first; -1 for anything not on a private LAN."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return -1
    if addr.version != 4 or addr.is_loopback or addr.is_link_local or any(addr in n for n in _VIRTUAL_NETS):
        return -1
    for rank, net in enumerate(("192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12")):
        if addr in ipaddress.ip_network(net):
            return rank
    return -1


def _interface_ips() -> List[str]:
    """IPv4 address of each real interface, or [] where the OS offers no
    stdlib way to ask (Windows)."""
    try:
        import fcntl
        import struct
    except ImportError:
        return []
    request = 0xC0206921 if sys.platform == "darwin" else 0x8915  # SIOCGIFADDR
    out: List[str] = []
    try:
        names = [name for _, name in socket.if_nameindex()]
    except OSError:
        return []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for name in names:
            if _VIRTUAL_IFACE_RE.match(name):
                continue
            try:
                res = fcntl.ioctl(s.fileno(), request, struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue
            out.append(socket.inet_ntoa(res[20:24]))
    return out


def _routed_ips() -> List[str]:
    found: List[str] = []
    for probe in _PRIVATE_PROBES:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))
                found.append(s.getsockname()[0])
        except OSError:
            continue
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    return found


def _lan_ips() -> List[str]:
    out: List[str] = []
    for ip in _interface_ips() or _routed_ips():
        if _lan_rank(ip) >= 0 and ip not in out:
            out.append(ip)
    return sorted(out, key=_lan_rank)


def lan_urls(host: str = None, port: int = None) -> List[str]:
    """Addresses other devices on the local network can open, or none while
    the server only listens on this machine."""
    host = _listen["host"] if host is None else host
    port = port or _listen["port"]
    if not port or is_loopback_host(host):
        return []
    ips = _lan_ips() if host in _ALL_INTERFACES else [host]
    return [f"{_listen['scheme']}://{f'[{ip}]' if ':' in ip else ip}:{port}" for ip in ips]


def listen_host() -> str:
    return _listen["host"]


def is_loopback_host(host: str) -> bool:
    return host in ("localhost", "::1") or host.startswith("127.")


def save_config_values(values: dict) -> None:
    """Write top-level keys to config.json and the live config together."""
    from channel.web.api.config import _settings_save_lock
    from config import conf, get_data_root

    with _settings_save_lock:
        file_cfg = _read_config_file_for_write()
        file_cfg.update(values)
        _write_config_file_for_write(os.path.join(get_data_root(), "config.json"), file_cfg)
        for key, value in values.items():
            conf()[key] = value


def public_url() -> str:
    from config import conf

    return (conf().get("web_public_url") or "").strip().rstrip("/")


def _behind_auth_proxy() -> bool:
    from config import conf

    return conf().get("web_auth_proxy") is True


def _public_url_fixed() -> bool:
    return bool((os.environ.get("WEB_PUBLIC_URL") or "").strip())


def _state(host: str = None, port: int = None) -> dict:
    host = _listen["host"] if host is None else host
    port = port or _listen["port"]
    proxied = _behind_auth_proxy()
    return {
        "status": "success",
        "public_url": public_url(),
        "public_url_fixed": _public_url_fixed(),
        "lan_urls": [] if proxied else lan_urls(host, port),
        "listen": {"host": host, "port": port},
        "listen_fixed": proxied,
        # The desktop app owns its backend's port.
        "port_fixed": os.environ.get("COW_DESKTOP") == "1",
        "local_only": is_loopback_host(host),
        "password_set": _is_password_enabled(),
    }


def _error(message: str, reason: str) -> str:
    return json.dumps({"status": "error", "message": message, "reason": reason})


class IntegrationsHandler:
    def GET(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        return json.dumps(_state())

    def PUT(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        try:
            data = json.loads(web.data() or b"{}")
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        if "public_url" in data and _public_url_fixed():
            return _error("public_url_fixed", "public_url_fixed")
        if ("web_host" in data or "web_port" in data) and _behind_auth_proxy():
            return _error("listen_fixed", "listen_fixed")
        if "public_url" in data:
            value = str(data.get("public_url") or "").strip().rstrip("/")
            if value and not _PUBLIC_URL_RE.match(value):
                return _error("invalid_public_url", "invalid_public_url")
            save_config_values({"web_public_url": value})
            logger.info(f"[Integrations] Public URL set to {value or '(page origin)'}")
        if "web_host" not in data and "web_port" not in data:
            return json.dumps(_state())
        host = str(data.get("web_host") or _listen["host"]).strip().strip("[]")
        try:
            port = int(data.get("web_port") or _listen["port"])
        except (TypeError, ValueError):
            port = 0
        reason = _host_problem(host) or _port_problem(host, port)
        if reason:
            return _error(reason, reason)
        from config import conf

        # Only what the owner changed: config.json may be shared with another
        # instance (the desktop app reads web_port from it).
        changes = {}
        if host != conf().get("web_host"):
            changes["web_host"] = host
        if port != _listen["port"]:
            changes["web_port"] = port
        if (host, port) == (_listen["host"], _listen["port"]) or not _listen["port"]:
            if changes:
                save_config_values(changes)
        else:
            from channel.web.core.channel import WebChannel

            # Saved only once the new address is bound, so a failed move does
            # not leave a config the next start cannot use.
            WebChannel().rebind(host, port, (lambda: save_config_values(changes)) if changes else None)
            logger.info(f"[Integrations] Moving to {host}:{port}")
        return json.dumps(_state(host, port))


def _port_problem(host: str, port: int) -> str:
    """Why the server cannot be moved to ``port``, or ''."""
    if not 0 < port < 65536:
        return "invalid_port"
    if port == _listen["port"]:
        return ""
    if os.environ.get("COW_DESKTOP") == "1":
        return "port_fixed"
    return "" if can_bind(host, port) else "port_in_use"


def _host_problem(host: str) -> str:
    """Why the server cannot be moved to listen on ``host``, or ''."""
    if host != "localhost":
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return "invalid_host"
    if is_loopback_host(host):
        return ""
    # Without a console password, listening beyond this machine would hand
    # the console and every management API to the network.
    if not _is_password_enabled():
        return "password_required"
    if host in _ALL_INTERFACES:
        return ""
    # An address this machine does not own fails to bind, and would keep
    # failing on every start once saved.
    return "" if can_bind(host, 0) else "unavailable_host"


def can_bind(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            # As the server binds: closed connections lingering in TIME_WAIT
            # do not hold the port. On Windows the option would let the
            # probe share a port another program is using.
            if sys.platform != "win32":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
    except OSError:
        return False
    return True
