"""A half-written mcp.json must not be read as "no servers configured".

`_load_mcp_configs` falls back to config.json whenever it cannot read mcp.json,
which is the right call at boot -- there is nothing running to lose. The
reconcile path is different: there the fallback reads as "the file declares no
servers", so every running server is torn down and the broken signature is
recorded as applied, after which the reload never retries.
"""

import json
import os
import threading
from types import SimpleNamespace

from agent.tools.mcp import service
from agent.tools.tool_manager import ToolManager
from config import conf

SERVER = {"name": "srv", "command": "npx", "args": [], "type": "stdio"}


class _FakeClient:
    def __init__(self):
        self.shutdowns = 0

    def shutdown(self):
        self.shutdowns += 1


class _FakeRegistry:
    def __init__(self, client=None):
        self._registry_lock = threading.Lock()
        self._shared_pool_lock = threading.Lock()
        self._shared_pool = {}
        self._clients = {"srv": client} if client else {}


def _manager(tmp_path, client):
    """A manager with one booted server, as if it had loaded a good file before."""
    manager = ToolManager.__new__(ToolManager)
    manager.workspace_root = str(tmp_path)
    manager._mcp_lock = threading.Lock()
    manager._mcp_registry = _FakeRegistry(client)
    manager._mcp_tool_instances = {"srv.echo": SimpleNamespace(server_name="srv")}
    manager._mcp_vector_lock = threading.Lock()
    manager._mcp_tool_vectors = {"srv.echo": [0.0]}
    manager._mcp_status = {"srv": "ready"}
    manager._mcp_active_configs = {"srv": dict(SERVER)}
    manager._mcp_signature = (0, "the-file-the-servers-came-from")
    return manager


def _write_raw(tmp_path, text):
    path = service.mcp_config_path(str(tmp_path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _write_json(tmp_path, payload):
    return _write_raw(tmp_path, json.dumps(payload))


def _no_config_json_servers(monkeypatch):
    """Pin the fallback, so the test cannot depend on the machine's config.json."""
    monkeypatch.setitem(conf(), "mcp_servers", [])


def test_a_half_written_file_does_not_tear_down_the_running_server(tmp_path, monkeypatch):
    _no_config_json_servers(monkeypatch)
    client = _FakeClient()
    manager = _manager(tmp_path, client)
    # What an editor leaves behind when it is interrupted mid-save.
    _write_raw(tmp_path, '{"mcpServers": {"srv": {"command": "np')

    manager.refresh_mcp_if_changed()

    assert client.shutdowns == 0, "a half-written file killed a healthy server"
    assert "srv.echo" in manager._mcp_tool_instances, "its tools were dropped too"
    assert manager._mcp_active_configs["srv"] == SERVER


def test_the_broken_signature_is_not_recorded_as_applied(tmp_path, monkeypatch):
    """Recording it would make the next refresh a no-op, so the fix never lands."""
    _no_config_json_servers(monkeypatch)
    manager = _manager(tmp_path, _FakeClient())
    _write_raw(tmp_path, '{"mcpServers": {')

    manager.refresh_mcp_if_changed()

    assert manager._mcp_signature == (0, "the-file-the-servers-came-from")


def test_the_reload_retries_once_the_file_is_valid_again(tmp_path, monkeypatch):
    _no_config_json_servers(monkeypatch)
    client = _FakeClient()
    manager = _manager(tmp_path, client)
    _write_raw(tmp_path, '{"mcpServers": {')
    manager.refresh_mcp_if_changed()

    _write_json(tmp_path, {"mcpServers": {}})
    manager.refresh_mcp_if_changed()

    assert client.shutdowns == 1, "the retry after the fix never ran"
    assert "srv.echo" not in manager._mcp_tool_instances


def test_a_valid_file_that_really_drops_the_server_still_tears_it_down(tmp_path, monkeypatch):
    """Control: the guard must not disable removal."""
    _no_config_json_servers(monkeypatch)
    client = _FakeClient()
    manager = _manager(tmp_path, client)
    _write_json(tmp_path, {"mcpServers": {}})

    manager.refresh_mcp_if_changed()

    assert client.shutdowns == 1
    assert "srv.echo" not in manager._mcp_tool_instances
    assert "srv" not in manager._mcp_status


def test_an_unchanged_server_is_left_running(tmp_path, monkeypatch):
    """Control: the common reload path still no-ops."""
    _no_config_json_servers(monkeypatch)
    client = _FakeClient()
    manager = _manager(tmp_path, client)
    _write_json(tmp_path, {"mcpServers": {"srv": {"command": "npx", "args": []}}})

    manager.refresh_mcp_if_changed()

    assert client.shutdowns == 0
    assert "srv.echo" in manager._mcp_tool_instances


def test_a_missing_file_still_falls_back(tmp_path, monkeypatch):
    """Control: boot behaviour is unchanged -- no file means config.json."""
    monkeypatch.setitem(conf(), "mcp_servers", [dict(SERVER)])
    manager = ToolManager.__new__(ToolManager)
    manager.workspace_root = str(tmp_path)

    assert [c["name"] for c in manager._load_mcp_configs()] == ["srv"]
