"""A request that comes back with no JSON-RPC response is a failed call.

``_streamable_http_post`` returns ``{}`` when a server answers ``202 Accepted``
(or 200 with an empty body) to a message that expected a reply. ``call_tool``
read that dict as a result, found no ``content`` and returned ``""``, so the
tool card and the executor's retry guard saw a successful call with no output.
A JSON-RPC response always carries exactly one of ``result`` or ``error``, so a
response with neither has to be reported as a failure.
"""

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.mcp.mcp_client import McpClient, McpToolCallError  # noqa: E402


def _client(response, transport="streamable-http"):
    """An McpClient whose transport returns a canned response."""
    c = McpClient.__new__(McpClient)
    c.name = "demo"
    c.transport = transport
    c._initialized = True
    c._send_request = lambda method, params: response
    return c


class _FakeHeaders(dict):
    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == str(key).lower():
                return value
        return default


class _FakeResponse:
    """A urlopen() result good enough for ``_streamable_http_post``."""

    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self._body = body
        self._read = False
        self.headers = _FakeHeaders(headers or {})

    def read(self):
        if self._read:
            return b""
        self._read = True
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _http_client(monkeypatch, response):
    """An streamable-http client whose urlopen() yields ``response``."""
    c = McpClient.__new__(McpClient)
    c.name = "demo"
    c.transport = "streamable-http"
    c._initialized = True
    c._http_url = "https://mcp.example.com/mcp"
    c._http_session_id = None
    c._http_headers = {}
    c._http_lock = threading.Lock()
    c._http_reinit_lock = threading.Lock()
    c._oauth = None
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: response,
    )
    return c


class TestAnEmptyResponseIsAFailedCall:
    def test_a_bare_202_becomes_a_tool_call_error(self):
        with pytest.raises(McpToolCallError, match="no JSON-RPC response"):
            _client({}).call_tool("search", {"q": "x"})

    def test_an_envelope_without_result_or_error_is_rejected(self):
        with pytest.raises(McpToolCallError, match="no JSON-RPC response"):
            _client({"jsonrpc": "2.0", "id": 1}).call_tool("search", {"q": "x"})

    def test_list_tools_reports_the_missing_response_in_the_log(self, caplog):
        client = _client({})
        with caplog.at_level("WARNING"):
            assert client.list_tools() == []
        assert any("no JSON-RPC response" in r.getMessage() for r in caplog.records)

    def test_a_202_to_a_request_reaches_call_tool_as_an_error(self, monkeypatch):
        # The source of the empty dict: a server that answers a request with
        # 202 Accepted and no body. Proof that the path is reachable, not just
        # inferable.
        client = _http_client(monkeypatch, _FakeResponse(202))
        assert client._streamable_http_post({"jsonrpc": "2.0", "id": 1}, True) == {}

        client._send_request = lambda method, params: client._streamable_http_post(
            {"jsonrpc": "2.0", "id": 1}, True
        )
        with pytest.raises(McpToolCallError, match="no JSON-RPC response"):
            client.call_tool("search", {"q": "x"})


class TestExistingShapesAreUnchanged:
    def test_a_null_result_is_still_an_empty_success(self):
        # result: null is legal JSON-RPC for a tool with no return value.
        assert _client({"jsonrpc": "2.0", "id": 1, "result": None}).call_tool(
            "noop", {}
        ) == ""

    def test_a_successful_tool_call_is_still_returned(self):
        out = _client(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "hi"}]}}
        ).call_tool("search", {"q": "x"})
        assert out == "hi"

    def test_an_rpc_error_still_names_the_server_message(self):
        with pytest.raises(McpToolCallError, match="Method not found"):
            _client(
                {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
            ).call_tool("search", {"q": "x"})
