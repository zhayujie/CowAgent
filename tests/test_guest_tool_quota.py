"""Guest writes and edits count only their net change toward storage quota."""

from unittest.mock import patch

import pytest

from agent.guest.paths import PathGuard
from agent.guest.tools import GuestTool
from agent.tools.edit.edit import Edit
from agent.tools.write.write import Write


@pytest.mark.parametrize("previous, content, limit, allowed", [
    ("0123456789", "x", 10, True),
    ("0123456789", "abcdefghij", 10, True),
    ("ééééé", "é", 10, True),
    ("1234", "123456", 6, True),
    ("1234", "1234567", 6, False),
    (None, "123456", 6, True),
    (None, "éééé", 6, False),
])
def test_write_checks_projected_usage(tmp_path, previous, content, limit, allowed):
    target = tmp_path / "notes.txt"
    if previous is not None:
        target.write_text(previous, encoding="utf-8")
    (tmp_path / "other.txt").write_text("abc", encoding="utf-8")
    guard = PathGuard.build(str(tmp_path))
    tool = GuestTool(Write(), guard, ["path"], write=True, max_work_bytes=limit + 3)

    result = tool.execute({"path": "/work/notes.txt", "content": content})

    assert result.status == ("success" if allowed else "error"), result.result
    if allowed:
        assert target.read_text(encoding="utf-8") == content
        assert guard.work_usage_bytes() <= limit + 3
    else:
        assert "storage is full" in result.result
        if previous is None:
            assert not target.exists()
        else:
            assert target.read_text(encoding="utf-8") == previous


@pytest.mark.parametrize("content, old_text, new_text, replace_all, limit, expected", [
    ("0123456789", "0123456789", "x", False, 10, "x"),
    ("ééééé", "ééééé", "x", False, 10, "x"),
    ("abc abc", "abc", "x", True, 7, "x x"),
    ("x x", "x", "é", True, 5, "é é"),
    ("x x", "x", "é", True, 4, None),
    ("abc", "a", "aa", False, 3, None),
    ("abc\n", "", "x", True, 4, None),
])
def test_edit_checks_projected_usage(tmp_path, content, old_text, new_text, replace_all, limit, expected):
    target = tmp_path / "notes.txt"
    target.write_text(content, encoding="utf-8")
    guard = PathGuard.build(str(tmp_path))
    tool = GuestTool(Edit(), guard, ["path"], write=True, max_work_bytes=limit)

    result = tool.execute({"path": "notes.txt", "oldText": old_text,
                           "newText": new_text, "replaceAll": replace_all})

    assert result.status == ("success" if expected is not None else "error"), result.result
    if expected is not None:
        assert target.read_text(encoding="utf-8") == expected
        assert guard.work_usage_bytes() <= limit
    else:
        assert "storage is full" in result.result
        assert target.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("error", [FileNotFoundError, PermissionError])
@pytest.mark.parametrize("inner, args, operation", [
    (Write(), {"content": "x"}, "agent.guest.tools.os.path.getsize"),
    (Edit(), {"oldText": "abc", "newText": "x", "replaceAll": True}, "agent.guest.tools.open"),
])
def test_unavailable_file_counts_as_zero_bytes(tmp_path, error, inner, args, operation):
    (tmp_path / "other.txt").write_text("abc", encoding="utf-8")
    guard = PathGuard.build(str(tmp_path))
    tool = GuestTool(inner, guard, ["path"], write=True, max_work_bytes=3)
    args = dict(args, path=str(tmp_path / "notes.txt"))

    with patch(operation, side_effect=error):
        # A failed size lookup must not grant space for a growing write.
        result = tool._check_quota(args)
    if inner.name == "write":
        assert "storage is full" in result
    else:
        assert result is None
