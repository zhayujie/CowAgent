"""A streamable-http entry pointed at an HTTP+SSE-only server falls back to SSE."""

import pytest

from agent.tools.mcp.mcp_client import McpClient, McpHttpStatusError


def _client():
    return McpClient({"name": "legacy", "type": "streamable-http", "url": "http://mcp.test/sse"})


def _reject_post_with(client, code):
    def post(message, expect_response, **_kwargs):
        raise McpHttpStatusError(f"streamable-http HTTP {code}: rejected", code)

    client._streamable_http_post = post


@pytest.mark.parametrize("code", [400, 404, 405])
def test_a_rejected_post_retries_with_the_sse_transport(code):
    client = _client()
    _reject_post_with(client, code)
    attempts = []

    def init_sse():
        attempts.append(client.transport)
        return True

    client._init_sse = init_sse

    assert client.initialize() is True
    assert attempts == ["sse"]
    assert client.transport == "sse"


@pytest.mark.parametrize("code", [403, 500, 502])
def test_other_statuses_do_not_fall_back(code):
    client = _client()
    _reject_post_with(client, code)
    client._init_sse = lambda: pytest.fail("must not fall back to SSE")

    assert client.initialize() is False
    assert client.transport == "streamable-http"
    assert f"HTTP {code}" in client.last_error


def test_a_failed_fallback_reports_both_reasons():
    client = _client()
    _reject_post_with(client, 405)

    def init_sse():
        client.last_error = "SSE endpoint discovery failed: boom"
        return False

    client._init_sse = init_sse

    assert client.initialize() is False
    assert client.transport == "streamable-http"
    assert "HTTP 405" in client.last_error and "boom" in client.last_error
