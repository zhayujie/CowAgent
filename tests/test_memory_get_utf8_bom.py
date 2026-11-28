"""memory_get should drop a UTF-8 BOM the same way the read tool does.

Windows editors often save markdown with a leading EF BB BF. The read tool
already opens files as utf-8-sig so that mark is not part of the first line.
memory_get used plain utf-8, so the first line of a BOM-prefixed memory or
knowledge note started with U+FEFF and a heading such as "# Preference" no
longer looked like a heading.
"""
from pathlib import Path

from agent.tools.memory.memory_get import MemoryGetTool
from agent.tools.read.read import split_lines


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


def test_a_utf8_bom_is_not_part_of_the_first_line(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_bytes(
        b"\xef\xbb\xbf# Preference\nI like tea.\n"
    )

    result = tool.execute({"path": "memory/notes.md"})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: 1-2 (total: 2)"
    assert body == "# Preference\nI like tea."
    assert not body.startswith("\ufeff")
    # Same first line the read tool would number after opening as utf-8-sig.
    expected = split_lines(
        (tmp_path / "memory" / "notes.md").read_text(encoding="utf-8-sig")
    )
    assert body.split("\n") == expected


def test_a_file_without_a_bom_is_unchanged(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text(
        "# Preference\nI like tea.\n", encoding="utf-8"
    )

    result = tool.execute({"path": "memory/notes.md"})

    assert result.status == "success"
    header, body = _header_and_body(result.result)
    assert header == "Lines: 1-2 (total: 2)"
    assert body == "# Preference\nI like tea."
