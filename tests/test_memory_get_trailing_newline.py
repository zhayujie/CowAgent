"""memory_get should not invent a line after a trailing newline.

The tool split file contents on "\\n", so a normal memory note ending in a
newline (what most editors write) reported one line too many and showed a
blank line past the end. An empty file was treated as a single blank line.
The read tool already drops that trailing empty element; memory_get should
do the same so line ranges and totals match the file.
"""
from pathlib import Path

from agent.tools.memory.memory_get import MemoryGetTool


class _Manager:
    def __init__(self, workspace):
        self.config = type("C", (), {"get_workspace": lambda s: Path(workspace)})()


def _tool(tmp_path):
    tool = MemoryGetTool.__new__(MemoryGetTool)
    tool.memory_manager = _Manager(str(tmp_path))
    return tool


def _header_and_body(result_text: str):
    lines = result_text.split("\n")
    # "File: ...", "Lines: ...", "", then body
    return lines[1], "\n".join(lines[3:])


def test_a_file_ending_in_a_newline_does_not_gain_a_phantom_line(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text("alpha\nbeta\n", encoding="utf-8")

    result = tool.execute({"path": "memory/notes.md"})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: 1-2 (total: 2)"
    assert body == "alpha\nbeta"


def test_a_file_without_a_trailing_newline_is_unchanged(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text("alpha\nbeta", encoding="utf-8")

    result = tool.execute({"path": "memory/notes.md"})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: 1-2 (total: 2)"
    assert body == "alpha\nbeta"


def test_an_empty_file_has_no_lines(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text("", encoding="utf-8")

    result = tool.execute({"path": "memory/notes.md"})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: none (total: 0)"
    assert body == ""


def test_a_file_that_is_only_a_newline_is_one_blank_line(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text("\n", encoding="utf-8")

    result = tool.execute({"path": "memory/notes.md"})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: 1-1 (total: 1)"
    assert body == ""


def test_a_real_blank_line_in_the_middle_is_kept(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text("alpha\n\nbeta\n", encoding="utf-8")

    result = tool.execute({"path": "memory/notes.md"})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: 1-3 (total: 3)"
    assert body == "alpha\n\nbeta"


def test_num_lines_stops_at_real_lines_not_the_phantom(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text("alpha\nbeta\n", encoding="utf-8")

    result = tool.execute({"path": "memory/notes.md", "start_line": 2, "num_lines": 1})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: 2-2 (total: 2)"
    assert body == "beta"
