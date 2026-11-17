"""Turns away what a web page on another site asks of this server.

The browser lets any page the user visits reach a server on this machine, even
one that listens on loopback only, and the agent behind it can run commands.
Two ways in are closed here, for every request before it reaches a handler:

- Cross-site writes. A page can send a POST here without asking first (a
  "simple" request), and it runs even though the page never sees the reply.
  Writes from another site are refused unless the site is listed in
  ``web_allowed_origins`` or the request carries the desktop shell's token.
  Native apps and scripts send no ``Origin`` or ``Sec-Fetch-Site`` and are
  left to the usual authentication.
- DNS rebinding. A domain the attacker controls can resolve to this machine,
  which makes the page same-origin with the server. Without a password nothing
  else stands in the way, so requests are then only served at ``localhost``,
  an IP address, the host of ``web_public_url`` or one listed in
  ``web_allowed_hosts``: the server can't tell any other name from one an
  attacker points here.
"""

import html
import ipaddress
import json
from dataclasses import dataclass, field
from typing import FrozenSet, Optional
from urllib.parse import urlsplit

from common.log import logger

_SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))
# Each with a cross-origin policy of its own: the OpenAI-compatible API has its
# own key and is open to other origins by design; guest pages carry their own
# token and can be embedded in other sites.
_OWN_POLICY_PREFIXES = ("/v1/", "/share/")


@dataclass(frozen=True)
class GuardPolicy:
    password_set: bool
    # Reached only through an authenticating proxy that owns the host names.
    behind_auth_proxy: bool = False
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


def refusal(environ: dict, policy: GuardPolicy, desktop_token_ok: bool = False) -> Optional[str]:
    """Why the request must be turned away, or None to let it through."""
    if not policy.password_set and not policy.behind_auth_proxy:
        name = _host_name(environ.get("HTTP_HOST", ""))
        if not _is_local_name(name) and name not in policy.allowed_hosts:
            return (f"Host '{name}' is not allowed while no web_password is set. "
                    f"Set web_password, or add it to web_allowed_hosts.")

    if (environ.get("REQUEST_METHOD") or "GET").upper() in _SAFE_METHODS:
        return None
    if (environ.get("PATH_INFO") or "").startswith(_OWN_POLICY_PREFIXES):
        return None
    if not _is_cross_site(environ) or desktop_token_ok:
        return None
    if _origin(environ.get("HTTP_ORIGIN", "")) in policy.allowed_origins:
        return None
    return "Cross-site request refused. Add the site to web_allowed_origins to allow it."


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
    if public_host:
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
        "<p>No access password is set, so the console only answers to addresses no other "
        "website can point at this machine. Either:</p>"
        "<ol><li>set an access password (<code>web_password</code>), or</li>"
        "<li>add this host name to <code>config.json</code> and restart:"
        f"<pre style='background:#f6f8fa;padding:12px;border-radius:6px'>{snippet}</pre></li></ol>"
        "</body></html>"
    )


def guard_requests(app):
    """WSGI middleware applying :func:`refusal` to every request."""
    from channel.web.core._common import _desktop_token_matches, _is_loopback_request

    def wrapped(environ, start_response):
        reason = refusal(
            environ,
            current_policy(),
            desktop_token_ok=_is_loopback_request(environ) and _desktop_token_matches(environ),
        )
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
