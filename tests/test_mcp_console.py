"""Web/desktop MCP + skill install console APIs."""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.tools.mcp.service import (
    McpConfigError,
    list_servers_with_status,
    load_servers,
    probe_server,
    save_servers,
    validate_server,
)
from agent.tools.tool_manager import ToolManager


ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_validate_stdio_requires_command():
    with pytest.raises(McpConfigError, match="command"):
        validate_server({"name": "fetch", "type": "stdio"})


def test_validate_sse_and_http_require_url():
    with pytest.raises(McpConfigError, match="url"):
        validate_server({"name": "remote", "type": "sse"})
    with pytest.raises(McpConfigError, match="url"):
        validate_server({"name": "remote", "type": "streamable-http"})


def test_validate_rejects_unknown_type_and_bad_name():
    with pytest.raises(McpConfigError, match="unsupported"):
        validate_server({"name": "x", "type": "ftp", "url": "https://example.com/mcp"})
    with pytest.raises(McpConfigError, match="name"):
        validate_server({"name": "../escape", "command": "npx"})


def test_validate_normalizes_http_aliases_and_infers_type():
    http = validate_server({"name": "pubmed", "type": "streamablehttp", "url": "https://x/mcp"})
    assert http["type"] == "streamable-http"
    inferred = validate_server({"name": "local", "command": "uvx", "args": ["mcp-server-fetch"]})
    assert inferred["type"] == "stdio"
    remote = validate_server({"name": "api", "url": "https://example.com/sse"})
    assert remote["type"] == "sse"


def test_save_writes_mcp_servers_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent.tools.mcp.service.mcp_config_path",
        lambda workspace=None: str(tmp_path / "mcp.json"),
    )
    saved = save_servers(str(tmp_path), [
        {"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]},
        {
            "name": "github",
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "tok"},
            "disabled": True,
        },
        {
            "name": "remote",
            "type": "http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer x"},
        },
    ])
    path = tmp_path / "mcp.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"mcpServers"}
    assert "name" not in payload["mcpServers"]["fetch"]
    assert payload["mcpServers"]["fetch"]["command"] == "uvx"
    assert payload["mcpServers"]["github"]["disabled"] is True
    assert payload["mcpServers"]["remote"]["type"] == "streamable-http"
    assert [item["name"] for item in saved] == ["fetch", "github", "remote"]
    loaded = load_servers(str(tmp_path))
    assert {item["name"] for item in loaded} == {"fetch", "github", "remote"}


def test_get_does_not_spawn_servers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent.tools.mcp.service.mcp_config_path",
        lambda workspace=None: str(tmp_path / "mcp.json"),
    )
    (tmp_path / "mcp.json").write_text(json.dumps({
        "mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}},
    }), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise AssertionError("GET must not construct an MCP client")

    monkeypatch.setattr("agent.tools.mcp.mcp_client.McpClient.__init__", boom)
    result = list_servers_with_status(str(tmp_path))
    assert result["servers"][0]["name"] == "fetch"
    assert result["servers"][0]["status"] == "idle"


def test_disabled_servers_are_not_booted(tmp_path):
    tm = ToolManager.__new__(ToolManager)
    tm.workspace_root = str(tmp_path)
    (tmp_path / "mcp.json").write_text(json.dumps({
        "mcpServers": {
            "off": {"command": "uvx", "args": ["mcp-server-fetch"], "disabled": True},
            "on": {"command": "uvx", "args": ["mcp-server-fetch"]},
        },
    }), encoding="utf-8")
    configs = tm._load_mcp_configs()
    assert [cfg["name"] for cfg in configs] == ["on"]


def test_test_endpoint_does_not_persist(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self, config):
            self.config = config
            self.needs_auth = False

        def initialize(self):
            return True

        def list_tools(self):
            return [{"name": "ping", "description": "pong"}]

        def shutdown(self):
            return None

    monkeypatch.setattr("agent.tools.mcp.mcp_client.McpClient", FakeClient)
    result = probe_server({"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]})
    assert result["ok"] is True
    assert result["tools"] == [{"name": "ping", "description": "pong"}]
    assert not (tmp_path / "mcp.json").exists()


def _get(handler_cls, params):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "input", return_value=web_channel.web.storage(**params)):
        return json.loads(handler_cls().GET())


def _send(handler_cls, method, body):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
        return json.loads(getattr(handler_cls(), method)())


def test_mcp_handlers_read_and_write_workspace_file(tmp_path, monkeypatch):
    from channel.web.web_channel import McpServersHandler, McpServerTestHandler

    monkeypatch.setattr(
        "agent.tools.mcp.service.mcp_config_path",
        lambda workspace=None: str(tmp_path / "mcp.json"),
    )
    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        listed = _get(McpServersHandler, {"agent_id": ""})
        assert listed["status"] == "success"
        assert listed["servers"] == []

        saved = _send(McpServersHandler, "PUT", {
            "servers": [{"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]}],
        })
        assert saved["status"] == "success"
        assert saved["servers"][0]["name"] == "fetch"
        payload = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8"))
        assert "fetch" in payload["mcpServers"]

        with patch("agent.tools.mcp.mcp_client.McpClient") as client_cls:
            client = client_cls.return_value
            client.initialize.return_value = True
            client.list_tools.return_value = [{"name": "fetch", "description": "get"}]
            client.needs_auth = False
            tested = _send(McpServerTestHandler, "POST", {
                "server": {"name": "probe", "command": "uvx", "args": ["mcp-server-fetch"]},
            })
        assert tested["ok"] is True
        assert tested["tools"][0]["name"] == "fetch"
        assert list(payload["mcpServers"]) == ["fetch"]


def test_skills_handler_install_and_delete(tmp_path):
    from channel.web.web_channel import SkillsHandler
    from cli.commands.skill import InstallResult

    fake = InstallResult()
    fake.installed = ["pptx"]
    fake.messages = ["installed pptx"]

    class DummyService:
        def __init__(self):
            self.deleted = []
            self.manager = type("M", (), {"refresh_skills": lambda self: None})()

        def query(self):
            return [{"name": "pptx", "deletable": True, "ships_with_install": False}]

        def delete(self, payload):
            self.deleted.append(payload["name"])

        def open(self, payload):
            return None

        def close(self, payload):
            return None

    dummy = DummyService()
    with patch("channel.web.web_channel._skill_service", return_value=dummy), \
         patch("channel.web.web_channel._install_skill_for_agent", return_value=fake):
        installed = _send(SkillsHandler, "POST", {"action": "install", "spec": "pptx"})
        deleted = _send(SkillsHandler, "POST", {"action": "delete", "name": "pptx"})

    assert installed["status"] == "success"
    assert installed["installed"] == ["pptx"]
    assert deleted["status"] == "success"
    assert dummy.deleted == ["pptx"]


def test_install_skill_for_agent_passes_agent_id_without_patching_global():
    import cli.commands.skill as skill_cmd
    from channel.web.web_channel import _install_skill_for_agent
    from cli.commands.skill import InstallResult

    original = skill_cmd.get_skills_dir
    fake = InstallResult()
    fake.installed = ["pptx"]
    with patch.object(skill_cmd, "install_skill", return_value=fake) as inst:
        result = _install_skill_for_agent("pptx", agent_id="other")

    assert skill_cmd.get_skills_dir is original
    inst.assert_called_once_with("pptx", agent_id="other")
    assert result.installed == ["pptx"]


def test_concurrent_install_skill_keeps_agent_dirs_isolated(tmp_path, monkeypatch):
    import cli.commands.skill as skill_cmd

    src_a = tmp_path / "src-a"
    src_b = tmp_path / "src-b"
    for src, name in ((src_a, "alpha"), (src_b, "beta")):
        src.mkdir()
        (src / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n# {name}\n",
            encoding="utf-8",
        )

    barrier = threading.Barrier(2)
    seen = []

    def fake_get_skills_dir(agent_id=None):
        seen.append(agent_id)
        barrier.wait(timeout=5)
        dest = tmp_path / (agent_id or "default") / "skills"
        dest.mkdir(parents=True, exist_ok=True)
        return str(dest)

    monkeypatch.setattr(skill_cmd, "get_skills_dir", fake_get_skills_dir)

    errors = []

    def run(spec, agent_id):
        try:
            result = skill_cmd.InstallResult()
            skill_cmd._install_local(str(spec), result, agent_id=agent_id)
            if result.error:
                errors.append(result.error)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=run, args=(src_a, "agent-a"))
    t2 = threading.Thread(target=run, args=(src_b, "agent-b"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    assert set(seen) == {"agent-a", "agent-b"}
    assert (tmp_path / "agent-a" / "skills" / "alpha" / "SKILL.md").exists()
    assert (tmp_path / "agent-b" / "skills" / "beta" / "SKILL.md").exists()
    assert not (tmp_path / "agent-a" / "skills" / "beta").exists()
    assert not (tmp_path / "agent-b" / "skills" / "alpha").exists()


def test_skills_handler_refuses_builtin_delete():
    from channel.web.web_channel import SkillsHandler

    class DummyService:
        def query(self):
            return [{"name": "core", "deletable": False, "ships_with_install": True}]

        def delete(self, payload):
            raise AssertionError("must not delete builtin")

    with patch("channel.web.web_channel._skill_service", return_value=DummyService()):
        response = _send(SkillsHandler, "POST", {"action": "delete", "name": "core"})
    assert response["status"] == "error"


def test_frontend_contract_exposes_mcp_and_skill_install_surfaces():
    html = _read("channel/web/chat.html")
    js = _read("channel/web/static/js/console.js")
    py = _read("channel/web/web_channel.py")
    desktop_page = _read("desktop/src/renderer/src/pages/SkillsPage.tsx")
    desktop_api = _read("desktop/src/renderer/src/api/client.ts")
    docs_en = _read("docs/tools/mcp.mdx")
    docs_zh = _read("docs/zh/tools/mcp.mdx")

    assert "'/api/mcp/servers', 'McpServersHandler'" in py
    assert "'/api/mcp/servers/test', 'McpServerTestHandler'" in py
    assert "action == \"install\"" in py
    assert "action == \"delete\"" in py

    for token in (
        'id="mcp-section"',
        'id="mcp-list"',
        'id="mcp-editor-overlay"',
        'id="skill-install-input"',
        'id="skill-install-btn"',
    ):
        assert token in html

    for token in (
        "function loadMcpSection",
        "/api/mcp/servers",
        "/api/mcp/servers/test",
        "action: 'install'",
        "action: 'delete'",
        "mcp_section_title:",
        "skill_install_btn:",
    ):
        assert token in js

    for token in (
        "getMcpServers",
        "saveMcpServers",
        "testMcpServer",
        "installSkill",
        "deleteSkill",
    ):
        assert token in desktop_api

    for token in (
        "mcp_section_title",
        "skill-install",
        "getMcpServers",
        "installSkill",
    ):
        assert token in desktop_page

    assert "web console" in docs_en.lower() or "Skills page" in docs_en
    assert "Test connection" in docs_en or "test connection" in docs_en.lower()
    assert "Web" in docs_zh or "web" in docs_zh.lower()
