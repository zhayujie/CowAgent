# encoding:utf-8
"""The web stream keeps an edit/write diff beside the short tool message."""

from channel.web.core.file_change import MAX_FILE_DIFF_CHARS, present_tool_result


def test_edit_result_keeps_the_diff_out_of_the_trace():
    diff = "--- original\n+++ modified\n@@ -1 +1 @@\n-old\n+new\n"
    text, change = present_tool_result({
        "message": "Successfully replaced text in notes.txt",
        "path": "notes.txt",
        "diff": diff,
        "first_changed_line": 1,
    })
    assert text == "Successfully replaced text in notes.txt"
    assert change["path"] == "notes.txt"
    assert change["diff"] == diff
    assert change["first_changed_line"] == 1
    assert change["truncated"] is False


def test_a_long_diff_is_capped_and_marked():
    diff = "--- original\n+++ modified\n@@ -1 +1 @@\n+" + ("x" * (MAX_FILE_DIFF_CHARS + 50))
    text, change = present_tool_result({"message": "wrote it", "path": "a.py", "diff": diff}, limit=100)
    assert text == "wrote it"
    assert len(change["diff"]) == 100
    assert change["truncated"] is True


def test_other_tools_stay_plain_text():
    text, change = present_tool_result("hello from bash")
    assert text == "hello from bash"
    assert change is None

    text, change = present_tool_result({"path": "a.py", "bytes_written": 3})
    assert change is None
    assert "bytes_written" in text


def test_stored_json_string_is_read_the_same_way():
    raw = '{"message": "ok", "path": "a.py", "diff": "--- original\\n+++ modified\\n@@ -1 +1 @@\\n-a\\n+b\\n"}'
    text, change = present_tool_result(raw)
    assert text == "ok"
    assert change["path"] == "a.py"
    assert change["diff"].startswith("---")
