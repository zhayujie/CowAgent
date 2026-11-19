"""Turns away what a web page on another site asks of this server.

The browser lets any page the user visits reach a server on this machine, even
one that listens on loopback only, and the agent behind it can run commands.
Two ways in are closed here, for every request before it reaches a handler:

- Cross-site writes. A page can send a POST here without asking first (a
  "simple" request), and it runs even though the page never sees the reply.
  Writes from another site are refused unless the site is listed in
  ``web_allowed_origins`` or the request carries the desktop shell's token.
  Native apps and scripts send no ``Origin`` or ``Sec-Fetch-Site`` and are
  left to the usual authentication. So is a write from a page without an
  origin (the desktop app talking to another machine) carrying a device token
  in its ``Authorization`` header: no other site can make the browser add it.
- DNS rebinding. A domain the attacker controls can resolve to this machine,
  which makes the page same-origin with the server. The server can't tell such
  a name from one of the user's own (a container name, a LAN or VPN host
  name), so this is opt-in: once ``web_allowed_hosts`` lists any name, a
  console without a password is only served at ``localhost``, an IP address,
  the host of ``web_public_url`` or a listed name. A password closes it too.

One kind of cross-site caller is let in: a console on another origin (say one
running on the user's own machine) that paired with this server. Pairing from
a page records the page's origin on the device; from then on that origin may
call here, reading the replies too, but only with that device's token. The
token sits in a header or the query string, never in a cookie, so no other
site can make the browser send it. Removing the device closes the origin.
"""

import html
import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import FrozenSet, Optional
from urllib.parse import parse_qs, urlsplit

from channel.web.core import devices
from common.log import logger

_SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))
# Each with a cross-origin policy of its own: the OpenAI-compatible API has its
# own key and is open to other origins by design; guest pages carry their own
# token and can be embedded in other sites.
_OWN_POLICY_PREFIXES = ("/v1/", "/share/")
# Open to a page on any origin: what this server is, and redeeming a pairing
# code, which is the credential itself (single use, short-lived, rate-limited).
# Signing in with the password is not: any site could then guess passwords, or
# lock the owner out, through its visitors' browsers.
_OPEN_PATHS = frozenset(("/.well-known/cowagent", "/auth/pair"))
_CORS_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
_CORS_HEADERS_RE = re.compile(r"^[A-Za-z0-9\-, ]{0,512}$")


@dataclass(frozen=True)
class GuardPolicy:
    password_set: bool
    # Reached only through an authenticating proxy that owns the host names.
    behind_auth_proxy: bool = False
    # Empty leaves host names unchecked.
    allowed_hosts: FrozenSet[str] = field(default_factory=frozenset)
    allowed_origins: FrozenSet[str] = field(default_factory=frozenset)


def _host_name(host: str) -> str:
    """``Host`` header without the port, lowercased; IPv6 brackets dropped."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _origin(value: str) -> str:
    """``scheme://host[:port]`` of a URL, lowercased; empty when it has none."""
    try:
        parts = urlsplit((value or "").strip())
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _is_local_name(name: str) -> bool:
    if not name or name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def _is_cross_site(environ: dict) -> bool:
    site = (environ.get("HTTP_SEC_FETCH_SITE") or "").strip().lower()
    if site:
        return site in ("cross-site", "same-site")
    # Browsers without Sec-Fetch-* still send Origin on a cross-origin write.
    origin = (environ.get("HTTP_ORIGIN") or "").strip()
    if not origin:
        return False
    netloc = urlsplit(origin).netloc.lower() if origin != "null" else ""
    hosts = {
        (environ.get("HTTP_HOST") or "").strip().lower(),
        (environ.get("HTTP_X_FORWARDED_HOST") or "").split(",")[0].strip().lower(),
    }
    return not netloc or netloc not in hosts


def cross_site_origin(environ: dict) -> str:
    """The calling page's origin, normalised, when the request crosses sites."""
    if not _is_cross_site(environ):
        return ""
    return devices.normalize_origin(environ.get("HTTP_ORIGIN", ""))


def _request_token(environ: dict) -> str:
    auth = environ.get("HTTP_AUTHORIZATION", "") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    try:
        values = parse_qs(environ.get("QUERY_STRING") or "").get("token") or [""]
    except Exception:
        return ""
    return values[-1] or ""


def cors_origin(environ: dict) -> str:
    """The ``Origin`` to allow in the reply, or "" to leave the request to
    the same-origin rules.

    A preflight carries no token, so it passes for any origin some device was
    paired from; the request that follows must carry that very device's token.
    """
    if (environ.get("PATH_INFO") or "").startswith(_OWN_POLICY_PREFIXES):
        return ""
    origin = cross_site_origin(environ)
    if not origin:
        return ""
    raw = _origin(environ.get("HTTP_ORIGIN", ""))
    if (environ.get("PATH_INFO") or "") in _OPEN_PATHS:
        return raw
    if _is_preflight(environ):
        return raw if devices.origin_allowed(origin) else ""
    device = devices.verify(_request_token(environ), ip=environ.get("REMOTE_ADDR", ""))
    return raw if device is not None and device.get("origin") == origin else ""


def _is_preflight(environ: dict) -> bool:
    return ((environ.get("REQUEST_METHOD") or "").upper() == "OPTIONS"
            and bool(environ.get("HTTP_ACCESS_CONTROL_REQUEST_METHOD")))


def _bearer_device_ok(environ: dict) -> bool:
    """A device token in the header, sent by a page with no web origin of its
    own (the desktop app's file:// page). Tokens of devices paired from a web
    page stay tied to that page's origin."""
    if (environ.get("HTTP_ORIGIN") or "null").strip() != "null":
        return False
    auth = environ.get("HTTP_AUTHORIZATION", "") or ""
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    if not token.startswith(devices.TOKEN_PREFIX):
        return False
    device = devices.verify(token, ip=environ.get("REMOTE_ADDR", ""))
    return device is not None and not device.get("origin")


def refusal(environ: dict, policy: GuardPolicy, desktop_token_ok: bool = False,
            cors_ok: bool = False, bearer_ok: bool = False) -> Optional[str]:
    """Why the request must be turned away, or None to let it through."""
    if policy.allowed_hosts and not policy.password_set and not policy.behind_auth_proxy:
        name = _host_name(environ.get("HTTP_HOST", ""))
        if not _is_local_name(name) and name not in policy.allowed_hosts:
            return (f"Host '{name}' is not allowed while no web_password is set. "
                    f"Set web_password, or add it to web_allowed_hosts.")

    if (environ.get("REQUEST_METHOD") or "GET").upper() in _SAFE_METHODS:
        return None
    if (environ.get("PATH_INFO") or "").startswith(_OWN_POLICY_PREFIXES):
        return None
    if not _is_cross_site(environ) or desktop_token_ok or cors_ok or bearer_ok:
        return None
    if _origin(environ.get("HTTP_ORIGIN", "")) in policy.allowed_origins:
        return None
    return "Cross-site request refused. Add the site to web_allowed_origins to allow it."


def _preflight_headers(environ: dict, origin: str) -> list:
    requested = environ.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS", "") or ""
    allow_headers = requested if requested and _CORS_HEADERS_RE.match(requested) else "Authorization, Content-Type"
    headers = [
        ("Access-Control-Allow-Origin", origin),
        ("Access-Control-Allow-Methods", _CORS_METHODS),
        ("Access-Control-Allow-Headers", allow_headers),
        ("Access-Control-Max-Age", "600"),
        ("Vary", "Origin, Access-Control-Request-Headers"),
        ("Content-Length", "0"),
    ]
    # Chrome asks before a page reaches an address more private than its own.
    if (environ.get("HTTP_ACCESS_CONTROL_REQUEST_PRIVATE_NETWORK") or "").lower() == "true":
        headers.append(("Access-Control-Allow-Private-Network", "true"))
    return headers


def _str_list(value) -> list:
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def current_policy() -> GuardPolicy:
    from channel.web.core._common import _is_password_enabled
    from common.deployment import is_managed
    from config import conf

    hosts = {h.lower() for h in _str_list(conf().get("web_allowed_hosts"))}
    public_host = urlsplit(_origin(conf().get("web_public_url", ""))).hostname
    if hosts and public_host:
        hosts.add(public_host)
    origins = {o for o in (_origin(v) for v in _str_list(conf().get("web_allowed_origins"))) if o}
    return GuardPolicy(
        password_set=_is_password_enabled(),
        behind_auth_proxy=is_managed(),
        allowed_hosts=frozenset(hosts),
        allowed_origins=frozenset(origins),
    )


def _refusal_page(reason: str, host: str) -> str:
    if not reason.startswith("Host "):
        return f"<!doctype html><meta charset='utf-8'><title>Refused</title><p>{html.escape(reason)}</p>"
    snippet = html.escape(json.dumps({"web_allowed_hosts": [host]}))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Host not allowed</title></head>"
        "<body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;"
        "margin:64px auto;padding:0 20px;color:#1f2328;line-height:1.6'>"
        f"<h2>This console isn't served at {html.escape(host)}</h2>"
        "<p>No access password is set and <code>web_allowed_hosts</code> limits the host "
        "names this console answers to. Either:</p>"
        "<ol><li>set an access password (<code>web_password</code>), or</li>"
        "<li>add this host name to <code>web_allowed_hosts</code> in <code>config.json</code> and restart:"
        f"<pre style='background:#f6f8fa;padding:12px;border-radius:6px'>{snippet}</pre></li></ol>"
        "</body></html>"
    )


def guard_requests(app):
    """WSGI middleware applying :func:`refusal` to every request."""
    from channel.web.core._common import _desktop_token_matches, _is_loopback_request

    def wrapped(environ, start_response):
        allowed_origin = cors_origin(environ)
        is_write = (environ.get("REQUEST_METHOD") or "GET").upper() not in _SAFE_METHODS
        reason = refusal(
            environ,
            current_policy(),
            desktop_token_ok=_is_loopback_request(environ) and _desktop_token_matches(environ),
            cors_ok=bool(allowed_origin),
            bearer_ok=is_write and _bearer_device_ok(environ),
        )
        if reason is None and allowed_origin and _is_preflight(environ):
            start_response("204 No Content", _preflight_headers(environ, allowed_origin))
            return [b""]
        if reason is None and allowed_origin:
            def start_with_cors(status, headers, exc_info=None):
                headers = list(headers) + [
                    ("Access-Control-Allow-Origin", allowed_origin),
                    ("Access-Control-Expose-Headers", "Content-Disposition, Retry-After"),
                    ("Vary", "Origin"),
                ]
                return start_response(status, headers, exc_info) if exc_info else start_response(status, headers)
            return app(environ, start_with_cors)
        if reason is None:
            return app(environ, start_response)
        logger.warning(
            f"[WebChannel] Refused {environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')} "
            f"(Host={environ.get('HTTP_HOST', '')}, Origin={environ.get('HTTP_ORIGIN', '')}): {reason}"
        )
        if "text/html" in (environ.get("HTTP_ACCEPT") or ""):
            body = _refusal_page(reason, _host_name(environ.get("HTTP_HOST", ""))).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            body = json.dumps({"status": "error", "message": reason}).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        start_response("403 Forbidden", [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    return wrapped
