# encoding:utf-8
"""Regression tests: writes/edits the memory index scans must mark it dirty.

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

``MEMORY.md`` at the workspace root is scanned too, and was missed for the same
reason. The check now resolves the path and compares segments against the
workspace, so all of these behave correctly.
"""

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.edit.edit import Edit
from agent.tools.write.write import Write
from channel.web.api import workspace as console_workspace


class _DirtyRecorder:
    """Minimal stand-in for MemoryManager that records mark_dirty() calls."""

    def __init__(self, workspace_root):
        self.config = SimpleNamespace(workspace_root=workspace_root)
        self.dirty_calls = 0

    def mark_dirty(self):
        self.dirty_calls += 1


class TestMemoryPathMarksDirty(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        # A real workspace has both; without a local knowledge/ the lookup
        # falls back to the shared one, which needs an Agent registry.
        os.makedirs(os.path.join(self.work, "memory"))
        os.makedirs(os.path.join(self.work, "knowledge"))
        self.memory_manager = _DirtyRecorder(self.work)

    def _tool_config(self):
        return {"cwd": self.work, "memory_manager": self.memory_manager}

    def _seed(self, *parts):
        """Create a file with two lines, for the edit tool to work on."""
        target = os.path.join(self.work, *parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("one\ntwo\n")
        return target

    # ---------------------------------------------------------------- write
    def test_write_to_knowledge_marks_dirty(self):
        """The bug: knowledge/ writes never dirtied the index."""
        result = Write(self._tool_config()).execute(
            {"path": "knowledge/note.md", "content": "# note\nbody\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_write_to_memory_marks_dirty(self):
        """The original behaviour must keep working."""
        result = Write(self._tool_config()).execute(
            {"path": "memory/2026-09-18.md", "content": "note\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_write_to_user_memory_marks_dirty(self):
        """Per-user memory sits deeper in the tree but is scanned all the same."""
        result = Write(self._tool_config()).execute(
            {"path": "memory/users/alice/2026-09-18.md", "content": "note\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_write_to_memory_file_marks_dirty(self):
        """MEMORY.md is indexed too, and contains no 'memory/' substring."""
        result = Write(self._tool_config()).execute(
            {"path": "MEMORY.md", "content": "# memory\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_write_absolute_path_marks_dirty(self):
        result = Write(self._tool_config()).execute(
            {"path": os.path.join(self.work, "knowledge", "abs.md"), "content": "x\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_write_to_unrelated_path_does_not_mark_dirty(self):
        result = Write(self._tool_config()).execute(
            {"path": "src/notes.md", "content": "x\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 0)

    def test_write_to_unrelated_path_containing_memory_segment(self):
        """'src/memory/cache.py' is not a memory file; the old substring test
        wrongly matched it."""
        result = Write(self._tool_config()).execute(
            {"path": "src/memory/cache.py", "content": "x = 1\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 0)

    @unittest.skipUnless(os.name == "nt", "backslash is only a separator on Windows")
    def test_write_backslash_separated_memory_path_marks_dirty(self):
        """'memory\\note.md' must match too. Elsewhere that is a single file
        name, not a path into memory/, and must not mark dirty."""
        result = Write(self._tool_config()).execute(
            {"path": "memory\\note.md", "content": "note\n"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    # ----------------------------------------------------------------- edit
    def test_edit_knowledge_marks_dirty(self):
        self._seed("knowledge", "note.md")
        result = Edit(self._tool_config()).execute(
            {"path": "knowledge/note.md", "oldText": "one", "newText": "ONE"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_edit_memory_marks_dirty(self):
        self._seed("memory", "2026-09-18.md")
        result = Edit(self._tool_config()).execute(
            {"path": "memory/2026-09-18.md", "oldText": "one", "newText": "ONE"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 1)

    def test_edit_unrelated_path_does_not_mark_dirty(self):
        self._seed("plain.txt")
        result = Edit(self._tool_config()).execute(
            {"path": "plain.txt", "oldText": "one", "newText": "ONE"}
        )
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(self.memory_manager.dirty_calls, 0)


class TestConsoleEditsMarkMemoryDirty(unittest.TestCase):
    """A human editing a memory file in the console must dirty the index too.

    ``POST /api/workspace/write`` does mark it, but it picked the files with a
    second, narrower copy of the check the tools use — ``MEMORY.md`` or a
    ``memory/`` prefix, with ``knowledge/`` left out. So a knowledge page saved
    from the console never re-embedded, and semantic search kept returning its
    pre-edit text (#3176, still open on this path).
    """

    def setUp(self):
        self.written = []
        self.dirty = []
        self.service = SimpleNamespace(write_text=self._record_write)

    def _record_write(self, rel, content, expected_mtime=None):
        self.written.append(rel)
        return {"path": rel, "size": len(content), "mtime": 1.0}

    def _save(self, rel, agent_id=None):
        """Drive the save handler with the seams it uses inside a request."""
        body = {"path": rel, "content": "edited\n"}
        if agent_id is not None:
            body["agent"] = agent_id
        with patch.object(console_workspace, "_require_auth", lambda: None), \
                patch.object(
                    console_workspace, "_editable_target",
                    lambda raw, sid=None, aid=None: (self.service, raw),
                ), \
                patch.object(
                    console_workspace, "_mark_memory_dirty", self.dirty.append
                ), \
                patch.object(console_workspace.web, "header", lambda *a, **k: None), \
                patch.object(
                    console_workspace.web, "data",
                    lambda: json.dumps(body).encode("utf-8"),
                ):
            return json.loads(console_workspace.WorkspaceWriteHandler().POST())

    def test_console_save_to_knowledge_marks_dirty(self):
        """The bug: knowledge/ pages saved from the console never dirtied it."""
        assert self._save("knowledge/note.md")["status"] == "success"

        assert self.written == ["knowledge/note.md"]
        assert self.dirty == [None]

    def test_console_save_to_nested_knowledge_marks_dirty(self):
        assert self._save("knowledge/concepts/moe.md")["status"] == "success"

        assert self.dirty == [None]

    def test_console_save_to_memory_marks_dirty(self):
        """The original behaviour must keep working."""
        assert self._save("memory/2026-09-20.md")["status"] == "success"

        assert self.dirty == [None]

    def test_console_save_to_memory_file_marks_dirty(self):
        """MEMORY.md is indexed too, and contains no 'memory/' substring."""
        assert self._save("MEMORY.md")["status"] == "success"

        assert self.dirty == [None]

    def test_console_save_forwards_the_agent(self):
        """The edit has to dirty the index of the agent that was edited."""
        assert self._save("knowledge/note.md", agent_id="ops")["status"] == "success"

        assert self.dirty == ["ops"]

    def test_console_save_to_unrelated_path_does_not_mark_dirty(self):
        assert self._save("src/notes.md")["status"] == "success"
        assert self._save("src/memory/cache.py")["status"] == "success"

        assert self.dirty == []

    def test_console_save_to_persona_files_does_not_mark_dirty(self):
        """AGENT.md / USER.md are editable system assets but are not indexed."""
        assert self._save("AGENT.md")["status"] == "success"
        assert self._save("USER.md")["status"] == "success"

        assert self.dirty == []

    @unittest.skipUnless(os.name == "nt", "backslash is only a separator on Windows")
    def test_console_save_with_backslash_separator_marks_dirty(self):
        """'knowledge\\note.md' must match too; elsewhere that is one file name."""
        assert self._save("knowledge\\note.md")["status"] == "success"

        assert self.dirty == [None]


if __name__ == "__main__":
    unittest.main()
