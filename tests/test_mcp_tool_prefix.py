"""MCP aliases must preserve built-ins and the server's original tool names."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.tools.mcp.mcp_client import McpClient
from agent.tools.mcp.mcp_tool import McpTool
from agent.tools.tool_manager import ToolManager
from agent.tools.web_fetch.web_fetch import WebFetch
from agent.tools.web_search.web_search import WebSearch
from config import conf


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setitem(conf(), "agent_workspace", str(tmp_path))
    tm = ToolManager()
    tm.tool_classes = {"web_search": WebSearch, "web_fetch": WebFetch}
    monkeypatch.setattr(McpClient, "initialize", lambda self: True)
    monkeypatch.setattr(McpClient, "list_tools", lambda self: [
        {"name": name, "description": "Remote tool", "inputSchema": {
            "type": "object", "properties": {"query": {"type": "string"}},
        }}
        for name in ("web_search", "web_fetch")
    ])
    yield tm
    tm.shutdown_mcp()


def load_server(manager, **options):
    from pathlib import Path

    Path(manager.workspace_root, "mcp.json").write_text(json.dumps({
        "mcpServers": {"search-server": {
            "type": "streamable-http", "url": "https://example.com/mcp",
            **options,
        }},
    }))
    manager._load_mcp_tools_async(manager._load_mcp_configs())
    assert manager.list_mcp_status() == {"search-server": "ready"}


@pytest.mark.parametrize("as_dict", [True, False])
def test_prefixed_tools_coexist_with_builtins_and_dispatch_remote_names(manager, as_dict):
    load_server(manager, tool_name_prefix="remote_")
    builtins = [manager.create_tool(name) for name in ("web_search", "web_fetch")]
    agent = SimpleNamespace(tools={t.name: t for t in builtins} if as_dict else builtins[:])

    assert manager.sync_mcp_into_agent(agent) == (["remote_web_fetch", "remote_web_search"], [])
    tools = agent.tools if as_dict else {t.name: t for t in agent.tools}
    assert set(tools) == {"web_search", "web_fetch", "remote_web_search", "remote_web_fetch"}
    for builtin in builtins:
        assert tools[builtin.name] is builtin
        remote = tools["remote_" + builtin.name]
        assert remote is manager.create_tool(remote.name)
        assert isinstance(remote, McpTool)
        assert remote.get_json_schema()["name"] == remote.name
        assert manager.list_tools()[remote.name]["parameters"] == remote.params
        remote.client.call_tool = Mock(return_value="remote result")
        arguments = {"query": "public information"}
        result = remote.execute(arguments)
        assert result.status == "success"
        assert result.result == "remote result"
        remote.client.call_tool.assert_called_once_with(builtin.name, arguments)

    manager._teardown_mcp_server("search-server")
    assert manager.sync_mcp_into_agent(agent) == ([], ["remote_web_fetch", "remote_web_search"])
    remaining = list(agent.tools.values()) if as_dict else agent.tools
    assert remaining == builtins


def test_prefix_change_removes_old_aliases(manager):
    load_server(manager, tool_name_prefix="first_")
    builtin = manager.create_tool("web_fetch")
    agent = SimpleNamespace(tools={"web_fetch": builtin})
    manager.sync_mcp_into_agent(agent)
    manager._teardown_mcp_server("search-server")
    load_server(manager, tool_name_prefix="second_")
    manager.sync_mcp_into_agent(agent)
    assert set(agent.tools) == {"web_fetch", "second_web_fetch", "second_web_search"}
    assert agent.tools["web_fetch"] is builtin


@pytest.mark.parametrize("options", [{}, {"tool_name_prefix": ""}])
def test_omitted_or_empty_prefix_preserves_existing_names(manager, options):
    load_server(manager, **options)
    agent = SimpleNamespace(tools={})
    manager.sync_mcp_into_agent(agent)
    assert set(agent.tools) == {"web_search", "web_fetch"}
    tool = agent.tools["web_search"]
    tool.client.call_tool = Mock(return_value="unchanged")
    assert tool.execute({}).result == "unchanged"
    tool.client.call_tool.assert_called_once_with("web_search", {})
