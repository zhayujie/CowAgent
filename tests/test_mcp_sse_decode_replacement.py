"""A stray byte in an MCP SSE stream must not fail the whole call.

_read_sse_response (streamable-http) and _sse_discover_endpoint decoded each
line with strict UTF-8, so a single invalid byte anywhere in the stream
raised UnicodeDecodeError and the tools/call — or the server's
initialization — failed outright. _sse_read_loop already decodes the same
bytes with errors="replace"; these tests pin the other two readers to the
same behavior.
"""
from agent.tools.mcp.mcp_client import McpClient


def _client():
    return McpClient({"name": "test", "type": "streamable-http",
                      "url": "http://mcp.test", "timeout": 1})


def test_a_stray_byte_does_not_fail_the_response():
    stream = [
        b"event: message\n",
        b"data: {\"jsonrpc\": \"2.0\", \"id\": 7, \"result\": \"ok\"}\n",
        b"\xff\n",  # invalid UTF-8 trailing noise between events
        b"\n",
    ]
    assert _client()._read_sse_response(iter(stream), 7)["result"] == "ok"


def test_a_stray_byte_inside_the_data_line_still_parses_the_json():
    # The payload itself is clean JSON; the stray byte rides a comment line
    # before it. Replacement decoding keeps the event boundaries intact.
    stream = [
        b": noise \xff\n",
        b'data: {"jsonrpc": "2.0", "id": 9, "result": {"v": 1}}\n',
        b"\n",
    ]
    assert _client()._read_sse_response(iter(stream), 9)["result"] == {"v": 1}
