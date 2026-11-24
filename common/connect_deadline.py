"""Bound how long opening a connection may take, the name lookup included.

urllib3, under the requests every model provider uses, applies the connect
timeout to each address a host resolves to in turn, and none at all to the
lookup. Where a host is blocked or its DNS answer is poisoned, a model request
can then hang for minutes before it fails, logging nothing while the user
watches a spinner. Here the lookup and every address tried share one budget:
the caller's connect timeout, and never more than CONNECT_BUDGET_SECONDS.

Only opening the connection is bounded. The TLS handshake and reading the
response keep the caller's timeouts, so a model that thinks for minutes before
its first token is unaffected.
"""

import socket
import threading
import time

CONNECT_BUDGET_SECONDS = 20.0
# Least time one address gets while the budget lasts, enough for a slow handshake.
MIN_ATTEMPT_SECONDS = 5.0

_DEFAULT = object()
_installed = False


def _budget(timeout) -> float:
    if isinstance(timeout, (int, float)) and timeout > 0:
        return min(float(timeout), CONNECT_BUDGET_SECONDS)
    return CONNECT_BUDGET_SECONDS


def _lookup(host: str, port, family, seconds: float):
    """getaddrinfo, given up on after ``seconds``. A lookup still running then finishes on its own."""
    outcome = {}

    def run():
        try:
            outcome["infos"] = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        except Exception as e:
            outcome["error"] = e

    worker = threading.Thread(target=run, name="connect-lookup", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise socket.gaierror(f"looking up {host} timed out after {seconds:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["infos"]


def create_connection(address, timeout=_DEFAULT, source_address=None, socket_options=None):
    """urllib3's ``create_connection``, with the lookup and all addresses sharing one deadline."""
    from urllib3.util.connection import _set_socket_options, allowed_gai_family

    host, port = address
    if host.startswith("["):
        host = host.strip("[]")
    budget = _budget(timeout)
    deadline = time.monotonic() + budget
    infos = _lookup(host, port, allowed_gai_family(), budget)

    error = None
    for i, (family, socktype, proto, _name, sockaddr) in enumerate(infos):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            error = None
            break
        # A silent address must not use up the time the rest need, as an IPv6
        # route that drops packets would ahead of a working IPv4 one.
        attempt = max(remaining / (len(infos) - i), min(remaining, MIN_ATTEMPT_SECONDS))
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            _set_socket_options(sock, socket_options)
            sock.settimeout(attempt)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            # The handshake and the request run on the caller's own timeout.
            caller_set = timeout is None or isinstance(timeout, (int, float))
            sock.settimeout(timeout if caller_set else socket.getdefaulttimeout())
            return sock
        except OSError as e:
            error = e
            if sock is not None:
                sock.close()
    if error is not None:
        raise error
    if not infos:
        raise OSError("getaddrinfo returns an empty list")
    raise socket.timeout(f"connecting to {host} timed out after {budget:.0f}s")


def install() -> bool:
    """Route urllib3's connections through ``create_connection``; True once in place."""
    global _installed
    if _installed:
        return True
    try:
        from urllib3.util import connection
        # Both helpers are urllib3 internals; without them leave urllib3 as it is.
        connection._set_socket_options
        connection.allowed_gai_family
    except (ImportError, AttributeError):
        return False
    connection.create_connection = create_connection
    _installed = True
    return True
