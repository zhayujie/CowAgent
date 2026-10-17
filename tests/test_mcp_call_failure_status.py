"""Real stdio failures must reach tool cards and the executor's retry guard."""
import sys
from contextlib import contextmanager

import pytest

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.mcp.mcp_client import McpClient
from agent.tools.mcp.mcp_tool import McpTool


_SERVER = """
import json, sys, time
mode = sys.argv[1]
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    if request['method'] == 'initialize':
        response = {'result': {'protocolVersion': '2024-11-05', 'capabilities': {},
                              'serverInfo': {'name': 'fixture', 'version': '1'}}}
    elif mode == 'disconnect':
        sys.exit(0)
    elif mode == 'timeout':
        time.sleep(5)
        continue
    elif mode == 'rpc-error':
        response = {'error': {'code': -32603, 'message': 'fixture backend unavailable'}}
    else:
        text = 'Error: is ordinary document text' if mode == 'error-text' else 'fixture success'
        response = {'result': {'content': [{'type': 'text', 'text': text}]}}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], **response}), flush=True)
"""


@contextmanager
def executor_for(mode):
    client = McpClient({
        "name": "failure-fixture", "type": "stdio", "command": sys.executable,
        "args": ["-u", "-c", _SERVER, mode], "timeout": 1,
    })
    assert client.initialize()
    child = client._proc
    events = []
    tool = McpTool(client, {"name": "fixture", "inputSchema": {"type": "object"}}, "failure-fixture")
    executor = AgentStreamExecutor(agent=None, model=None, system_prompt="", tools=[tool], on_event=events.append)
    try:
        yield executor, events, client
    finally:
        client.shutdown()
        assert child.poll() is not None


@pytest.mark.parametrize("mode, detail", [
    ("rpc-error", "fixture backend unavailable"),
    ("disconnect", "closed unexpectedly"),
    ("timeout", "timed out"),
])
def test_native_call_failure_reaches_executor_status(mode, detail):
    with executor_for(mode) as (executor, events, _client):
        result = executor._execute_tool({"id": "call", "name": "fixture", "arguments": {}})
        assert result["status"] == "error", result
        assert detail in result["result"]
        assert executor.tool_failure_history[-1][2] is False
        end = [event["data"] for event in events if event["type"] == "tool_execution_end"]
        assert len(end) == 1
        assert end[0]["status"] == "error"
        assert detail in end[0]["result"]


@pytest.mark.parametrize("mode, text", [
    ("success", "fixture success"),
    ("error-text", "Error: is ordinary document text"),
])
def test_successful_text_is_not_classified_by_prefix(mode, text):
    with executor_for(mode) as (executor, events, _client):
        result = executor._execute_tool({"id": "call", "name": "fixture", "arguments": {}})
        assert result["status"] == "success"
        assert result["result"] == text
        assert executor.tool_failure_history[-1][2] is True
        assert events[-1]["data"]["status"] == "success"


def test_native_rpc_failures_activate_retry_guard_before_a_fourth_call():
    with executor_for("rpc-error") as (executor, events, client):
        for index in range(3):
            executor._execute_tool({"id": str(index), "name": "fixture", "arguments": {}})
        next_id = client._next_id
        result = executor._execute_tool({"id": "fourth", "name": "fixture", "arguments": {}})
        assert result["status"] == "error", result
        assert client._next_id == next_id
        assert len([event for event in events if event["type"] == "tool_execution_start"]) == 3
