# encoding:utf-8
"""workspace-write must not let a session rewrite the files that widen its own reach."""

import pytest

from agent.permission.policy import FULL_ACCESS, WORKSPACE_WRITE, check_tool_call


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "mcp.json").write_text("{}")
    (tmp_path / "skills").mkdir()
    return tmp_path


def _check(ws, tool, args, mode=WORKSPACE_WRITE):
    return check_tool_call(mode, tool, args, cwd=str(ws), write_roots=[str(ws)],
                           protected_paths=[str(ws / "mcp.json"), str(ws / "session_prefs.json")])


@pytest.mark.parametrize("tool,args", [
    ("write", {"path": "mcp.json"}),
    ("edit", {"path": "./skills/../mcp.json"}),
    ("write", {"path": "session_prefs.json"}),
    ("bash", {"command": "echo '{}' > mcp.json"}),
    ("bash", {"command": "cat evil.json | tee mcp.json"}),
    ("bash", {"command": "cp /tmp/evil.json mcp.json"}),
    ("bash", {"command": "cp /tmp/x/mcp.json ."}),
    ("bash", {"command": "mv /tmp/x/session_prefs.json ./"}),
    ("bash", {"command": "sed -i s/a/b/ mcp.json"}),
    ("bash", {"command": "Set-Content mcp.json x"}),
    ("bash", {"command": "Copy-Item source.txt mcp.json"}),
    ("bash", {"command": "Rename-Item mcp.json backup.json"}),
])
def test_protected_files_are_refused(ws, tool, args):
    decision = _check(ws, tool, args)
    assert not decision.allowed
    assert "full-access" in decision.reason


@pytest.mark.parametrize("tool,args", [
    ("write", {"path": "skills/demo/SKILL.md"}),
    ("bash", {"command": "cat mcp.json"}),
    ("bash", {"command": "cp mcp.json skills/backup.json"}),
    ("bash", {"command": "cp /tmp/x/mcp.json skills/"}),
])
def test_other_writes_and_reads_still_pass(ws, tool, args):
    assert _check(ws, tool, args).allowed


def test_full_access_is_untouched(ws):
    assert _check(ws, "write", {"path": "mcp.json"}, mode=FULL_ACCESS).allowed


def test_agent_protects_its_mcp_config_and_session_settings(ws, monkeypatch):
    from agent.protocol.agent import Agent

    monkeypatch.setattr("common.state_dir.shared_root", lambda: ws)
    agent = Agent.__new__(Agent)
    agent.workspace_dir = str(ws)
    paths = agent.protected_paths()
    assert str(ws / "mcp.json") in paths
    assert str(ws / "session_prefs.json") in paths
    assert str(ws / ".env") in paths


def test_symlink_to_a_protected_file_is_refused(ws):
    (ws / "link.json").symlink_to(ws / "mcp.json")
    assert not _check(ws, "write", {"path": "link.json"}).allowed
