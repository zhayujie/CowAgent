"""add_memory's file metadata must carry the indexing time, not the source file's mtime.

update_file_metadata received ``int(os.path.getmtime(__file__))`` with a
comment saying "Use current time" — __file__ is manager.py itself, so every
dynamically indexed memory row carried the module's install/update date as
its mtime. Nothing reads files.mtime for logic today, but the first
incremental-sync heuristic built on it would treat all dynamic memory as
older than it is.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.manager import MemoryManager


class TestAddMemoryMtime(unittest.TestCase):

    def test_add_memory_records_the_indexing_wall_clock(self):
        import asyncio

        manager = object.__new__(MemoryManager)
        recorded = {}

        class FakeStorage:
            def save_chunks_batch(self, chunks):
                pass

            def update_file_metadata(self, **kwargs):
                recorded.update(kwargs)

        manager.storage = FakeStorage()
        from agent.memory.chunker import TextChunker

        manager.chunker = TextChunker()
        manager.embedding_provider = None

        before = time.time()
        asyncio.run(manager.add_memory("hello world", source="test", path="memory/shared/m1.md"))
        after = time.time()

        self.assertGreaterEqual(recorded["mtime"], int(before))
        self.assertLessEqual(recorded["mtime"], int(after) + 1)


if __name__ == "__main__":
    unittest.main()
