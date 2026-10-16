"""HTTPS and reverse-proxy support for the web console.

Two deployment stories, both opt-in:

1. Direct HTTPS. Set ``web_https_enabled`` plus ``web_ssl_certfile`` /
   ``web_ssl_keyfile`` and the console serves TLS itself through cheroot's
   ``BuiltinSSLAdapter``. Useful for a quick domain deployment without a
   separate proxy.

2. Reverse proxy (nginx, Caddy, Traefik, ...). Terminate TLS at the proxy and
   point it at the console's plain-HTTP port. Set ``web_trust_proxy=true`` so
   the app sees the real client scheme/host/IP from the ``X-Forwarded-*``
   headers the proxy adds, and optionally ``web_external_url`` so absolute
   URLs (e.g. the MCP OAuth callback) use the public domain.

``web_trust_proxy`` must only be enabled when the console is reachable
exclusively through the proxy: the forwarded headers are trivially spoofable
by any client that can reach the console directly.
"""

import os
from typing import Callable, Optional, Tuple


def _first_forwarded(value: Optional[str]) -> str:
    """First entry of a comma-separated forwarded header value.

    Proxies append to these headers, so the leftmost entry is the original
    client value and anything after it was added downstream.
    """
    if not value:
        return ""
    return value.split(",")[0].strip()


class TrustProxyMiddleware:
    """WSGI middleware that applies ``X-Forwarded-*`` headers.

    Only installed when ``web_trust_proxy`` is true (see module docstring).
    Rewrites the WSGI environ so the app -- and anything it builds from the
    request, like redirect URLs or ``request.host`` -- sees the public-facing
    scheme, host, and client IP instead of the proxy's internal hop.
    """

    def __init__(self, app: Callable):
        self.app = app

    def __call__(self, environ: dict, start_response: Callable):
        proto = _first_forwarded(environ.get("HTTP_X_FORWARDED_PROTO", ""))
        if proto:
            environ["wsgi.url_scheme"] = proto.lower()
        host = _first_forwarded(environ.get("HTTP_X_FORWARDED_HOST", ""))
        if host:
            environ["HTTP_HOST"] = host
        forwarded_for = _first_forwarded(environ.get("HTTP_X_FORWARDED_FOR", ""))
        if forwarded_for:
            environ["REMOTE_ADDR"] = forwarded_for
        return self.app(environ, start_response)


def resolve_tls_config(
    https_enabled: bool,
    certfile: str,
    keyfile: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Validate the direct-HTTPS config; return ``(certfile, keyfile)``.

    Returns ``(None, None)`` when HTTPS is disabled. Raises ``ValueError``
    with an actionable message when it is enabled but misconfigured, so a
    bad path fails fast at startup instead of serving plain HTTP silently.
    """
    if not https_enabled:
        return None, None
    certfile = (certfile or "").strip()
    keyfile = (keyfile or "").strip()
    if not certfile:
        raise ValueError(
            "web_https_enabled is true but web_ssl_certfile is empty; "
            "set it to the PEM certificate file (full chain recommended)"
        )
    if not keyfile:
        raise ValueError(
            "web_https_enabled is true but web_ssl_keyfile is empty; "
            "set it to the PEM private key file"
        )
    for label, path in (("web_ssl_certfile", certfile), ("web_ssl_keyfile", keyfile)):
        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            raise ValueError(
                f"{label} points at {path!r}, which is not a readable file"
            )
    return os.path.expanduser(certfile), os.path.expanduser(keyfile)


def build_ssl_adapter(certfile: str, keyfile: str):
    """Build cheroot's TLS adapter for the given PEM files.

    Imported lazily so a missing cheroot install only breaks the HTTPS path,
    not the whole web channel. Raises ``RuntimeError`` with a clear message
    when cheroot is unavailable.
    """
    try:
        from cheroot.ssl.builtin import BuiltinSSLAdapter
    except ImportError as e:
        raise RuntimeError(
            "web_https_enabled needs cheroot (it ships with web.py>=0.62); "
            f"could not import it: {e}"
        )
    return BuiltinSSLAdapter(certfile, keyfile)
