from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_web_backend_exposes_agent_and_core_file_routes():
    source = _read("channel/web/web_channel.py")
    assert "'/api/agents', 'AgentsHandler'" in source
    assert "'/api/agents/([^/]+)/files/([^/]+)', 'AgentCoreFileHandler'" in source
    assert "class AgentsHandler:" in source
    assert "class AgentCoreFileHandler:" in source


def test_console_has_agent_selector_workspace_manager_and_core_files():
    html = _read("channel/web/chat.html")
    assert 'id="agent-selector"' in html
    assert 'id="view-agents"' in html
    assert 'id="agents-list"' in html
    assert 'id="agent-core-editor"' in html
    for filename in ("AGENT.md", "USER.md", "RULE.md", "MEMORY.md", "BOOTSTRAP.md"):
        assert f"<option>{filename}</option>" in html


def test_console_carries_agent_id_through_existing_feature_requests():
    source = _read("channel/web/static/js/console.js")
    assert "body.agent_id = activeAgentId" in source
    assert "agent_id=${encodeURIComponent(activeAgentId)}" in source
    assert "function selectActiveAgent(agentId)" in source
    assert "function runtimeSessionKey" in source


def test_workspace_scoped_web_services_resolve_selected_agent():
    source = _read("channel/web/web_channel.py")
    assert "def _get_workspace_root(agent_id: str = None)" in source
    assert "get_conversation_store(_get_workspace_root(agent_id))" in source
    assert "KnowledgeService(_get_workspace_root(agent_id))" in source
    assert "get_scheduler_service(agent_id=agent_id)" in source
    assert "for profile in get_agent_registry().list()" in source
