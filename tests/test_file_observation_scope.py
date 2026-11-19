"""One conversation's fresh read must not replace another's stale file view."""

import os

import pytest

from agent.tools.edit.edit import Edit
from agent.tools.read.read import Read
from agent.tools.utils import file_state
from agent.tools.write.write import Write
from common.runtime_identity import identity_scope


@pytest.fixture(autouse=True)
def isolated_observations():
    file_state.reset()
    yield
    file_state.reset()


def observed_file(tmp_path):
    path = tmp_path / "report.txt"
    path.write_text("first line\nold second line\n", encoding="utf-8")
    os.utime(path, (1700000000, 1700000000))
    with identity_scope(agent_id="writer", session_id="chat-A"):
        assert (
            Read({"cwd": str(tmp_path)}).execute({"path": str(path)}).status
            == "success"
        )
    path.write_text("first line\nupdated outside\n", encoding="utf-8")
    os.utime(path, (1700000002, 1700000002))
    return path


@pytest.mark.parametrize(
    "other",
    [
        {"agent_id": "writer", "session_id": "chat-B"},
        {"agent_id": "teammate", "session_id": "chat-A"},
    ],
)
@pytest.mark.parametrize("tool", ["edit", "write"])
@pytest.mark.parametrize("other_action", ["read", "write"])
def test_other_observation_does_not_hide_original_conversations_warning(
    tmp_path, other, tool, other_action
):
    path = observed_file(tmp_path)
    with identity_scope(**other):
        if other_action == "read":
            result = Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
            assert "updated outside" in result.result["content"]
        else:
            result = Write({"cwd": str(tmp_path)}).execute(
                {"path": str(path), "content": "first line\nwritten by other actor\n"}
            )
            assert result.status == "success"
    with identity_scope(agent_id="writer", session_id="chat-A"):
        if tool == "edit":
            result = Edit({"cwd": str(tmp_path)}).execute(
                {
                    "path": str(path),
                    "oldText": "first line",
                    "newText": "revised first line",
                }
            )
        else:
            result = Write({"cwd": str(tmp_path)}).execute(
                {"path": str(path), "content": "revised first line\nold second line\n"}
            )
        assert result.status == "success", result.result
        assert "modified after you last read it" in result.result.get("warning", "")
        assert file_state.staleness_warning(str(path)) is None


def test_unread_conversation_has_no_borrowed_expectation(tmp_path):
    path = observed_file(tmp_path)
    with identity_scope(agent_id="writer", session_id="chat-B"):
        result = Write({"cwd": str(tmp_path)}).execute(
            {"path": str(path), "content": "new document\n"}
        )
    assert result.status == "success"
    assert "warning" not in result.result


def test_same_conversation_keeps_observation_across_turns(tmp_path):
    path = tmp_path / "report.txt"
    path.write_text("initial\n", encoding="utf-8")
    os.utime(path, (1700000000, 1700000000))
    with identity_scope(agent_id="writer", session_id="chat-A", run_id="first-turn"):
        Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
    path.write_text("outside edit\n", encoding="utf-8")
    os.utime(path, (1700000002, 1700000002))
    with identity_scope(agent_id="writer", session_id="chat-A", run_id="next-turn"):
        assert "modified after you last read it" in file_state.staleness_warning(
            str(path)
        )


def test_same_conversation_reread_refreshes_its_own_view(tmp_path):
    path = observed_file(tmp_path)
    with identity_scope(agent_id="writer", session_id="chat-A"):
        assert (
            Read({"cwd": str(tmp_path)}).execute({"path": str(path)}).status
            == "success"
        )
        result = Write({"cwd": str(tmp_path)}).execute(
            {"path": str(path), "content": "new content based on fresh read\n"}
        )
    assert result.status == "success"
    assert "warning" not in result.result
