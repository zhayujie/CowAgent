"""
Shared SSRF guard utilities for tools that fetch model-supplied URLs.

SSRF protection is OPT-IN and disabled by default, because legitimate use
cases (local dev servers, LAN services, proxy fake-ip resolution) need to
reach non-public addresses. Enable it by setting the config option
``web_security_ssrf_protection: true`` (or env ``WEB_SECURITY_SSRF_PROTECTION``).

When enabled, a URL is only considered safe when it uses an http/https
scheme, has a hostname, that hostname resolves, and every resolved address
is a public (internet-routable) address. Loopback, private (RFC1918 / ULA),
link-local (incl. the 169.254.169.254 cloud-metadata endpoint) and otherwise
reserved addresses are rejected, for both IPv4 and IPv6.
"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

import requests


def _ssrf_protection_enabled() -> bool:
    """Return True only when SSRF protection is explicitly turned on.

    Disabled by default. Reads the env var first, then falls back to the
    global config; any failure to read config is treated as "disabled" so
    the guard never breaks normal fetching.
    """
    env = os.getenv("WEB_SECURITY_SSRF_PROTECTION")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        from config import conf
        return bool(conf().get("web_security_ssrf_protection", False))
    except Exception:
        return False


def _is_blocked_ip(ip: "ipaddress._BaseAddress") -> bool:
    """Return True if the address is not safe to connect to (non-public)."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_ip(ip_str: str) -> None:
    """Raise ValueError if the given literal IP is a non-public address.

    No-op when SSRF protection is disabled (the default). Used to re-validate
    the concrete address a redirect resolved to.
    """
    if not _ssrf_protection_enabled():
        return
    ip = ipaddress.ip_address(ip_str)
    if _is_blocked_ip(ip):
        raise ValueError(
            f"URL resolves to a non-public address ({ip_str}), "
            f"request blocked for security"
        )


def validate_url_safe(url: str) -> None:
    """Reject URLs that target private/loopback/link-local addresses (SSRF guard).

    No-op when SSRF protection is disabled (the default). When enabled,
    resolves the hostname to its IP address(es) and blocks any that fall
    into non-public ranges. Also rejects URLs with no host, non-HTTP(S)
    schemes, or hosts that fail DNS resolution.

    Raises:
        ValueError: if the URL targets a disallowed address.
    """
    if not _ssrf_protection_enabled():
        return

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    try:
        # Resolve all addresses for the hostname.
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in addr_infos:
        assert_public_ip(sockaddr[0])


# Cap on how many redirects we follow; every hop's target is re-validated
# against the SSRF guard so a public URL cannot bounce us into an internal one.
MAX_REDIRECTS = 10


def safe_get(url: str, timeout: float = 30, headers: dict = None,
             max_redirects: int = MAX_REDIRECTS, **kwargs) -> "requests.Response":
    """Issue a GET request while re-validating every redirect hop (SSRF guard).

    Auto-redirect is disabled and each hop is followed manually, so the target
    of every redirect is re-resolved and checked against the SSRF guard before
    it is requested. This prevents a public URL from 3xx-bouncing into a
    private, loopback, link-local or cloud-metadata address. Extra ``kwargs``
    are passed through to ``requests.get`` (e.g. ``stream``).

    Any tool that fetches a model-supplied URL must go through this helper:
    validating only the original URL leaves the redirect hop unguarded.

    Raises:
        ValueError: if any hop resolves to a non-public address.
    """
    kwargs.pop("allow_redirects", None)
    current = url
    for _ in range(max_redirects + 1):
        response = requests.get(
            current,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            **kwargs,
        )
        if not response.is_redirect and not response.is_permanent_redirect:
            return response

        location = response.headers.get("Location")
        if not location:
            return response

        # Resolve the redirect target relative to the current URL, then
        # re-validate it before following.
        current = requests.compat.urljoin(current, location)
        validate_url_safe(current)
        response.close()

    raise ValueError(f"Too many redirects (>{max_redirects})")
