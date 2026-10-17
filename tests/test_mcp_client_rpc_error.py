"""Regression: an MCP server's JSON-RPC error envelope must reach the model.

A JSON-RPC error has no "result" key, so list_tools()/call_tool() used to read it
as an empty success: the server's own message was dropped and the model was told
the server had no tools / the tool returned nothing."""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.mcp.mcp_client import McpClient, McpToolCallError  # noqa: E402


def _client(response):
    """An McpClient whose transport returns a canned response."""
    c = McpClient.__new__(McpClient)
    c.name = "demo"
    c.transport = "stdio"
    c._initialized = True
    c._send_request = lambda method, params: response
    return c


RPC_ERROR = {
    "jsonrpc": "2.0",
    "id": 1,
    "error": {"code": -32601, "message": "Method not found: tools/call"},
}

OK_TOOLS = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {"tools": [{"name": "search", "description": "d",
                          "inputSchema": {"type": "object"}}]},
}

OK_CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {"content": [{"type": "text", "text": "hello"}]},
}


class TestMcpRpcErrorIsSurfaced:
    def test_list_tools_stays_empty_but_the_error_is_logged(self):
        records = []

        class _Grab(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        from common.log import logger as cow_logger

        records = []

        class _Grab(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        # common.log sets propagate = False, so the handler has to go on the
        # project logger itself, not on the root logger.
        handler = _Grab()
        cow_logger.addHandler(handler)
        prev = cow_logger.level
        cow_logger.setLevel(logging.WARNING)
        try:
            out = _client(RPC_ERROR).list_tools()
        finally:
            cow_logger.removeHandler(handler)
            cow_logger.setLevel(prev)
        assert out == []
        assert any("Method not found" in m for m in records), records

    def test_call_tool_tells_the_model_about_the_error(self):
        with pytest.raises(McpToolCallError, match="Method not found") as failure:
            _client(RPC_ERROR).call_tool("search", {"q": "x"})
        assert str(failure.value).startswith("Error:")

    def test_a_null_result_is_not_treated_as_an_error(self):
        # result: null is legal JSON-RPC for a tool with no return value.
        out = _client({"jsonrpc": "2.0", "id": 1, "result": None}).call_tool("noop", {})
        assert out == ""

    def test_a_successful_tools_list_is_unchanged(self):
        out = _client(OK_TOOLS).list_tools()
        assert [t["name"] for t in out] == ["search"]

    def test_a_successful_tool_call_is_unchanged(self):
        assert _client(OK_CALL).call_tool("search", {"q": "x"}) == "hello"
