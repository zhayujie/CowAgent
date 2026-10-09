"""File changes survive the tool result and conversation-history boundaries."""

import json

from agent.memory.conversation_store import _group_into_display_turns
from common.file_change import MAX_FILE_CHANGE_DIFF_CHARS, file_change_from_result
from agent.tools.write.write import Write


def test_write_returns_diff_for_new_and_overwritten_files(tmp_path):
    tool = Write({"cwd": str(tmp_path)})
    created = tool.execute({"path": "note.txt", "content": "first\n"})
    assert created.status == "success"
    assert "+first" in created.result["diff"]

    changed = tool.execute({"path": "note.txt", "content": "second\n"})
    assert changed.status == "success"
    assert "-first" in changed.result["diff"]
    assert "+second" in changed.result["diff"]


def test_saved_file_change_is_reconstructed_as_structured_step():
    tool_result = {"path": "note.txt", "diff": "--- original\n+++ modified\n@@ -1 +1 @@\n-old\n+new", "first_changed_line": 1}
    rows = [
        ("user", json.dumps("change the note"), 1, None),
        ("assistant", json.dumps([{"type": "tool_use", "id": "t1", "name": "edit", "input": {"path": "note.txt"}}]), 2, None),
        ("user", json.dumps([{"type": "tool_result", "tool_use_id": "t1", "content": json.dumps(tool_result)}]), 3, None),
        ("assistant", json.dumps([{"type": "text", "text": "Done."}]), 4, None),
    ]

    turns = _group_into_display_turns(rows)
    step = turns[-1]["steps"][0]
    assert step["file_change"] == {**tool_result, "truncated": False}


def test_only_valid_file_results_get_structured_diffs():
    result = {"path": "note.txt", "diff": "+new", "first_changed_line": 1}
    assert file_change_from_result("bash", result) is None
    assert file_change_from_result("edit", "not JSON") is None
    assert file_change_from_result("write", {"path": "note.txt"}) is None
    assert file_change_from_result("write", json.dumps(result)) == {
        **result, "truncated": False,
    }


def test_large_diff_is_explicitly_marked_as_shortened():
    change = file_change_from_result("edit", {
        "path": "large.txt", "diff": "x" * (MAX_FILE_CHANGE_DIFF_CHARS + 1),
    })
    assert len(change["diff"]) == MAX_FILE_CHANGE_DIFF_CHARS
    assert change["truncated"] is True
