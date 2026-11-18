"""memory_get's auto-prefix must understand Windows paths.

The check used startswith('/') as its absolute-path test and literal
'memory/'/'knowledge/' prefixes. On Windows the model echoes paths with
backslashes: 'memory\\notes.md' was misprefixed into 'memory/memory\\notes.md'
and 'C:\\Users\\me\\notes.md' into 'memory/C:\\Users\\me\\notes.md' — existing
files then reported as missing, with a path string that misleads the model
into thinking they were deleted.

The backslash-prefix case is observable on every platform; the drive-letter
case is pinned by borrowing ntpath.isabs for the duration of the call.
"""
import ntpath
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.memory.memory_get import MemoryGetTool


class _Manager:
    def __init__(self, workspace):
        from pathlib import Path

        self.config = type("C", (), {"get_workspace": lambda s: Path(workspace)})()


def _tool(tmp_path):
    tool = MemoryGetTool.__new__(MemoryGetTool)
    tool.memory_manager = _Manager(str(tmp_path))
    return tool


def test_backslash_memory_prefix_is_recognized(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "notes.md").write_text("body", encoding="utf-8")

    with patch.object(os.path, "isabs", ntpath.isabs):
        result = tool.execute({"path": "memory\\notes.md"})

    assert "Error" not in str(result.result)


def test_drive_letter_absolute_path_is_not_prefixed(tmp_path):
    tool = _tool(tmp_path)
    # Nowhere for C:\\... to resolve on this box; what matters is that the
    # error is a plain missing-file report, not 'memory/C:\\...'.
    with patch.object(os.path, "isabs", ntpath.isabs):
        result = tool.execute({"path": "C:\\Users\\me\\notes.md"})

    assert "memory/C:" not in str(result.result)


def test_a_leading_slash_is_not_prefixed_under_ntpath(tmp_path):
    tool = _tool(tmp_path)
    # ntpath.isabs('/x') is False on Python 3.13+, so the slash check must stay.
    with patch.object(os.path, "isabs", ntpath.isabs):
        result = tool.execute({"path": "/srv/notes.md"})

    assert "memory/" not in str(result.result)


def test_posix_behaviour_is_unchanged(tmp_path):
    tool = _tool(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "n.md").write_text("body", encoding="utf-8")

    result = tool.execute({"path": "n.md"})

    assert "Error" not in str(result.result)
