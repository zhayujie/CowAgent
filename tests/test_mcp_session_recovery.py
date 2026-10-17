"""Regression tests for Streamable HTTP session recovery."""

import json
import threading
import urllib.error
from email.message import Message
from io import BytesIO
from unittest.mock import patch

import pytest

from agent.tools.mcp.mcp_client import McpClient, McpToolCallError


class _Response:
    def __init__(self, payload=None, *, session_id=None, status=200):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        if session_id:
            self.headers["Mcp-Session-Id"] = session_id
        self._body = json.dumps(payload).encode() if payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def _http_error(request):
    return urllib.error.HTTPError(
        request.full_url,
        404,
        "Not Found",
        Message(),
        BytesIO(b"Session not found"),
    )


def _request_payload(request):
    return json.loads(request.data.decode())


def _client():
    client = McpClient(
        {"name": "test", "type": "streamable-http", "url": "http://mcp.test"}
    )
    client._http_url = "http://mcp.test"
    client._http_session_id = "expired"
    client._initialized = True
    return client


def test_reinitializes_and_retries_after_expired_session():
    client = _client()
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        payload = _request_payload(request)
        session_id = request.headers.get("Mcp-session-id")

        if session_id == "expired":
            raise _http_error(request)
        if payload["method"] == "initialize":
            return _Response(
                {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                session_id="replacement",
            )
        if payload["method"] == "notifications/initialized":
            return _Response(status=202)
        return _Response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"content": [{"type": "text", "text": "pong"}]},
            }
        )

    with patch("urllib.request.urlopen", side_effect=urlopen):
        assert client.call_tool("ping", {}) == "pong"

    methods = [_request_payload(request)["method"] for request, _ in requests]
    assert methods == [
        "tools/call",
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert client._http_session_id == "replacement"
    assert requests[-1][0].headers["Mcp-session-id"] == "replacement"


def test_does_not_reinitialize_404_without_a_session():
    client = _client()
    client._http_session_id = None

    def urlopen(request, timeout):
        raise _http_error(request)

    with patch("urllib.request.urlopen", side_effect=urlopen):
        with pytest.raises(McpToolCallError, match="HTTP 404"):
            client.call_tool("ping", {})

    assert client._http_session_id is None


def test_concurrent_failures_share_one_replacement_handshake():
    client = _client()
    barrier = threading.Barrier(2)
    request_lock = threading.Lock()
    initialize_count = 0

    def urlopen(request, timeout):
        nonlocal initialize_count
        payload = _request_payload(request)
        session_id = request.headers.get("Mcp-session-id")

        if session_id == "expired":
            barrier.wait(timeout=2)
            raise _http_error(request)
        if payload["method"] == "initialize":
            with request_lock:
                initialize_count += 1
            return _Response(
                {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                session_id="replacement",
            )
        if payload["method"] == "notifications/initialized":
            return _Response(status=202)
        return _Response(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"content": [{"type": "text", "text": "pong"}]},
            }
        )

    results = []
    with patch("urllib.request.urlopen", side_effect=urlopen):
        threads = [
            threading.Thread(target=lambda: results.append(client.call_tool("ping", {})))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

    assert results == ["pong", "pong"]
    assert initialize_count == 1
    assert client._http_session_id == "replacement"
