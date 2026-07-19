import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_multi_agent_guides_cover_workspace_isolation_and_delegation():
    for path in (
        "docs/guide/multi-agent.mdx",
        "docs/zh/guide/multi-agent.mdx",
        "docs/ja/guide/multi-agent.mdx",
    ):
        text = _read(path)
        assert "memory/long-term/index.db" in text
        assert "agent_delegate" in text
        assert "BOOTSTRAP.md" in text


def test_docs_navigation_lists_all_multi_agent_guides():
    navigation = json.loads(_read("docs/docs.json"))
    serialized = json.dumps(navigation, ensure_ascii=False)
    for page in (
        "guide/multi-agent",
        "zh/guide/multi-agent",
        "ja/guide/multi-agent",
    ):
        assert page in serialized


def test_default_config_documents_safe_delegation_limits():
    config = json.loads(_read("config-template.json"))
    assert config["agent_delegation"] == {
        "enabled": True,
        "max_depth": 3,
        "timeout_seconds": 120,
        "max_message_chars": 8000,
    }
