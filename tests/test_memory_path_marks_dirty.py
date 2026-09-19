# encoding:utf-8
"""Regression tests: writes/edits under ``memory/`` and ``knowledge/`` must
mark the memory index dirty.

The write and edit tools used to decide this with ``'memory/' in path`` — a
substring test against the raw argument. That missed three cases:

1. **``knowledge/`` is never matched**, so knowledge writes left the index
   stale. Retrieval only re-syncs when the manager is dirty, so freshly written
   knowledge stayed invisible to search until something else happened to dirty
   the index (#3176).
2. On Windows the tool may receive ``memory\\note.md``; the ``memory/`` needle
   never matches a backslash-separated path.
3. The substring matches anywhere in the path, so an unrelated file such as
   ``src/memory/cache.py`` was (harmlessly but wrongly) treated as a memory
   file.

The check is now made against the resolved absolute path, by comparing path
segments — so all three behave correctly.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.edit.edit import Edit
from agent.tools.write.write import Write


class _DirtyRecorder:
    """Minimal stand-in for MemoryManager that records mark_dirty() calls."""

    def __init__(self):
        self.dirty_calls = 0

    def mark_dirty(self):
        self.dirty_calls += 1


class TestMemoryPathMarksDirty(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()

    def _write_tool(self):
        self.memory_manager = _DirtyRecorder()
        return Write({"cwd": self.work, "memory_manager": self.memory_manager})

    def _edit_tool(self):
        self.memory_manager = _DirtyRecorder()
        return Edit({"cwd": self.work, "memory_manager": self.memory_manager})

    # ---------------------------------------------------------------- write
    def test_write_to_knowledge_marks_dirty(self):
        """The bug: knowledge/ writes never dirtied the index."""
        tool = self._write_tool()
        result = tool.execute(
            {"path": "knowledge/note.md", "content": "# note\nbody\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_write_to_memory_marks_dirty(self):
        """The original behaviour must keep working."""
        tool = self._write_tool()
        result = tool.execute(
            {"path": "memory/2026-09-18.md", "content": "note\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_write_to_unrelated_path_does_not_mark_dirty(self):
        tool = self._write_tool()
        result = tool.execute({"path": "src/notes.md", "content": "x\n"})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 0)

    def test_write_to_unrelated_path_containing_memory_segment(self):
        """'src/memory/cache.py' is not a memory file; the old substring test
        wrongly matched it."""
        tool = self._write_tool()
        os.makedirs(os.path.join(self.work, "src", "memory"))
        result = tool.execute({"path": "src/memory/cache.py", "content": "x = 1\n"})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 0)

    def test_write_backslash_separated_memory_path_marks_dirty(self):
        """'memory\\note.md' must match too (Windows separator)."""
        tool = self._write_tool()
        result = tool.execute({"path": "memory\\note.md", "content": "note\n"})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    # ----------------------------------------------------------------- edit
    def test_edit_knowledge_marks_dirty(self):
        path = os.path.join(self.work, "knowledge")
        os.makedirs(path)
        target = os.path.join(path, "note.md")
        with open(target, "w", encoding="utf-8") as f:
            f.write("one\ntwo\n")

        tool = self._edit_tool()
        result = tool.execute(
            {"path": "knowledge/note.md", "oldText": "one", "newText": "ONE"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_edit_memory_marks_dirty(self):
        path = os.path.join(self.work, "memory")
        os.makedirs(path)
        target = os.path.join(path, "2026-09-18.md")
        with open(target, "w", encoding="utf-8") as f:
            f.write("one\ntwo\n")

        tool = self._edit_tool()
        result = tool.execute(
            {"path": "memory/2026-09-18.md", "oldText": "one", "newText": "ONE"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_edit_unrelated_path_does_not_mark_dirty(self):
        target = os.path.join(self.work, "plain.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("one\ntwo\n")

        tool = self._edit_tool()
        result = tool.execute(
            {"path": "plain.txt", "oldText": "one", "newText": "ONE"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 0)


if __name__ == "__main__":
    unittest.main()
