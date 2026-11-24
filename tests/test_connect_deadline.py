"""Opening a connection, name lookup included, fails within one budget.

A model request to a host that is blocked or whose DNS answer is poisoned used
to hang for minutes: urllib3 gave each resolved address the full connect
timeout in turn, and the lookup none at all.
"""

import http.server
import socket
import threading
import time

import pytest
import requests
from urllib3.util import connection

from agent.protocol.agent_stream import _is_unreachable_error
from common import connect_deadline


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.setattr(connect_deadline, "CONNECT_BUDGET_SECONDS", 0.3)
    return 0.3


@pytest.fixture
def hanging_lookup(monkeypatch):
    release = threading.Event()

    def getaddrinfo(*args, **kwargs):
        release.wait(5)
        raise socket.gaierror("released")

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    release.set()


@pytest.fixture
def local_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_a_hanging_lookup_fails_within_the_budget(budget, hanging_lookup):
    started = time.monotonic()
    with pytest.raises(socket.gaierror, match="timed out"):
        connect_deadline.create_connection(("model.example", 443), timeout=15)
    assert time.monotonic() - started < budget + 1


def test_every_address_shares_one_budget(budget, monkeypatch):
    attempts = []

    class SilentSocket:
        def __init__(self, *args):
            self.timeout = None

        def settimeout(self, value):
            self.timeout = value

        def connect(self, sockaddr):
            attempts.append(sockaddr)
            time.sleep(self.timeout)
            raise socket.timeout("timed out")

        def close(self):
            pass

    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (f"10.0.0.{i}", 443)) for i in range(5)]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: addresses)
    monkeypatch.setattr(socket, "socket", SilentSocket)

    started = time.monotonic()
    with pytest.raises(socket.timeout):
        connect_deadline.create_connection(("model.example", 443), timeout=15)
    # Five addresses at 15s each used to mean 75s; now they share 0.3s.
    assert time.monotonic() - started < budget + 1
    assert len(attempts) == 1


def test_a_silent_address_leaves_time_for_the_next(budget, monkeypatch):
    monkeypatch.setattr(connect_deadline, "MIN_ATTEMPT_SECONDS", 0.05)

    class Socket:
        def __init__(self, *args):
            self.timeout = None

        def settimeout(self, value):
            self.timeout = value

        def connect(self, sockaddr):
            if sockaddr[0] == "2001:db8::1":
                time.sleep(self.timeout)
                raise socket.timeout("timed out")

        def close(self):
            pass

    addresses = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: addresses)
    monkeypatch.setattr(socket, "socket", Socket)

    assert connect_deadline.create_connection(("model.example", 443), timeout=15)


def test_the_callers_shorter_timeout_wins(monkeypatch):
    assert connect_deadline._budget(5) == 5
    assert connect_deadline._budget(60) == connect_deadline.CONNECT_BUDGET_SECONDS
    assert connect_deadline._budget(None) == connect_deadline.CONNECT_BUDGET_SECONDS


def test_a_reachable_server_keeps_the_callers_timeout(local_server):
    sock = connect_deadline.create_connection(("127.0.0.1", local_server), timeout=7)
    try:
        # The TLS handshake and the first read run on the caller's timeout, not what was left of the budget.
        assert sock.gettimeout() == 7
    finally:
        sock.close()


def test_requests_still_reaches_a_server(monkeypatch, local_server):
    monkeypatch.setattr(connection, "create_connection", connect_deadline.create_connection)
    response = requests.get(f"http://127.0.0.1:{local_server}/", timeout=(5, 5))
    assert response.status_code == 200
    assert response.text == "ok"


def test_requests_reports_a_hanging_lookup_as_unreachable(monkeypatch, budget, hanging_lookup):
    monkeypatch.setattr(connection, "create_connection", connect_deadline.create_connection)
    started = time.monotonic()
    with pytest.raises(requests.exceptions.ConnectionError) as caught:
        requests.post("https://model.example/v1/chat", json={}, timeout=(15, 900))
    assert time.monotonic() - started < budget + 2
    assert _is_unreachable_error(str(caught.value).lower())


def test_install_routes_urllib3_through_the_deadline(monkeypatch):
    monkeypatch.setattr(connect_deadline, "_installed", False)
    monkeypatch.setattr(connection, "create_connection", connection.create_connection)
    assert connect_deadline.install()
    assert connection.create_connection is connect_deadline.create_connection
