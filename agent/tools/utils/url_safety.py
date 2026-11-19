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

import contextvars
import ipaddress
import os
import socket
from contextlib import contextmanager
from typing import Iterable, Optional
from urllib.parse import urlparse

import requests

# Set by strict_url_guard() for the code running inside it: SSRF protection is
# forced on there, and hosts may be further limited to an allowlist.
_STRICT_GUARD: contextvars.ContextVar = contextvars.ContextVar("cow_strict_url_guard", default=None)


@contextmanager
def strict_url_guard(allowed_domains: Optional[Iterable[str]] = None):
    """Force SSRF protection for the calls made inside this block.

    ``allowed_domains`` (when non-empty) also restricts every URL, redirect
    hops included, to those hosts and their subdomains. Used for callers that
    act on behalf of someone less trusted than the person running the
    instance, regardless of the instance-wide SSRF setting.
    """
    domains = tuple(d.strip().lower().lstrip(".") for d in (allowed_domains or ()) if d and d.strip())
    token = _STRICT_GUARD.set({"domains": domains})
    try:
        yield
    finally:
        _STRICT_GUARD.reset(token)


def host_allowed(hostname: str, domains: Iterable[str]) -> bool:
    """Whether ``hostname`` is one of ``domains`` or a subdomain of one."""
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    for domain in domains:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _ssrf_protection_enabled() -> bool:
    """Return True only when SSRF protection is explicitly turned on.

    Disabled by default. Reads the env var first, then falls back to the
    global config; any failure to read config is treated as "disabled" so
    the guard never breaks normal fetching.
    """
    if _STRICT_GUARD.get() is not None:
        return True
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
        # Anything else outside the public range, e.g. the 100.64.0.0/10
        # shared address space, which is_private does not cover and which
        # hosts Alibaba Cloud's 100.100.100.200 metadata service.
        or not ip.is_global
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


def _ip_literal(hostname: str):
    """The address when ``hostname`` is written as an IP, otherwise None."""
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def validate_url_safe(url: str) -> None:
    """Reject URLs that target private/loopback/link-local addresses (SSRF guard).

    No-op when SSRF protection is disabled (the default). When enabled:

    - A host on ``strict_url_guard``'s domain allowlist is trusted by name.
      Local DNS is not consulted: proxies often return a synthetic address
      for every name, which is not the host the request will reach.
    - Any other host is resolved and every address must be public.
    - A URL whose host is a literal non-public IP is always refused.

    Also rejects URLs with no host or a non-HTTP(S) scheme.

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

    guard = _STRICT_GUARD.get()
    ip = _ip_literal(hostname)
    if ip is not None:
        if _is_blocked_ip(ip):
            raise ValueError(
                f"URL resolves to a non-public address ({hostname}), "
                f"request blocked for security"
            )
        if guard and guard["domains"] and not host_allowed(hostname, guard["domains"]):
            raise ValueError(f"Host {hostname} is not in the allowed domain list")
        return

    if guard and guard["domains"]:
        if not host_allowed(hostname, guard["domains"]):
            raise ValueError(f"Host {hostname} is not in the allowed domain list")
        return

    try:
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
        try:
            current = requests.compat.urljoin(current, location)
            validate_url_safe(current)
        finally:
            # A rejected redirect is never returned to the caller, so it must
            # release its connection here even when resolution/validation fails.
            response.close()

    raise ValueError(f"Too many redirects (>{max_redirects})")
