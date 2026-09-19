# encoding: utf-8
"""
Tests for chunker-version tracking:
  - _meta key/value round-trip (storage.get_meta / set_meta)
  - detect_chunker_version returns None on an unstamped (legacy) index and the
    recorded version once stamped
  - MemoryManager.sync() stamps chunker_version when it (re)builds from an
    EMPTY index (fresh install / after rebuild-index), and leaves an existing
    non-empty index unstamped so /memory status can flag it for a rebuild.
"""
import os
import sys
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.storage import MemoryStorage
from agent.memory.embedding.state import detect_chunker_version
from agent.memory.chunker import TextChunker


class TestMetaKV(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.storage = MemoryStorage(Path(self.dir) / "index.db")

    def tearDown(self):
        self.storage.close()

    def test_unset_meta_returns_none(self):
        self.assertIsNone(self.storage.get_meta("chunker_version"))

    def test_set_get_roundtrip(self):
        self.storage.set_meta("chunker_version", "1")
        self.assertEqual(self.storage.get_meta("chunker_version"), "1")

    def test_overwrite(self):
        self.storage.set_meta("chunker_version", "1")
        self.storage.set_meta("chunker_version", "2")
        self.assertEqual(self.storage.get_meta("chunker_version"), "2")


class TestDetectChunkerVersion(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.storage = MemoryStorage(Path(self.dir) / "index.db")

    def tearDown(self):
        self.storage.close()

    def test_detect_none_when_unstamped(self):
        # A legacy index (or any pre-version index) has no flag -> None,
        # which /memory status treats as "built by an older strategy".
        self.assertIsNone(detect_chunker_version(self.storage))

    def test_detect_matches_when_stamped(self):
        self.storage.set_meta("chunker_version", str(TextChunker.CHUNKER_VERSION))
        self.assertEqual(
            detect_chunker_version(self.storage), TextChunker.CHUNKER_VERSION
        )

    def test_detect_mismatch_for_old_version(self):
        self.storage.set_meta("chunker_version", str(TextChunker.CHUNKER_VERSION - 1))
        self.assertNotEqual(
            detect_chunker_version(self.storage), TextChunker.CHUNKER_VERSION
        )


class TestSyncStampsVersion(unittest.TestCase):
    """MemoryManager.sync stamps chunker_version only when starting from an
    empty index."""

    def _make(self, ws):
        import config
        config.load_config()
        from agent.memory.config import MemoryConfig
        from agent.memory.manager import MemoryManager
        from agent.memory.embedding.provider import EmbeddingProvider

        class FakeEmbed(EmbeddingProvider):
            @property
            def dimensions(self):
                return 3

            def embed(self, text):
                return [0.1, 0.2, 0.3]

            def embed_batch(self, texts):
                return [self.embed(t) for t in texts]

        mc = MemoryConfig(workspace_root=ws)
        return MemoryManager(mc, embedding_provider=FakeEmbed())

    def test_sync_from_empty_stamps(self):
        ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(ws, "knowledge", "infra"))
        with open(os.path.join(ws, "knowledge", "infra", "a.md"), "w",
                  encoding="utf-8") as f:
            f.write("# A\n\n内容。" * 400)  # >1500 -> triggers heading path
        m = self._make(ws)
        asyncio.run(m.sync(force=True))
        self.assertEqual(
            m.storage.get_meta("chunker_version"),
            str(TextChunker.CHUNKER_VERSION),
        )

    def test_sync_nonempty_does_not_overwrite_stamp(self):
        ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(ws, "knowledge", "infra"))
        with open(os.path.join(ws, "knowledge", "infra", "a.md"), "w",
                  encoding="utf-8") as f:
            f.write("# A\n\n内容。" * 400)
        m = self._make(ws)
        # First (empty->full) sync stamps v1.
        asyncio.run(m.sync(force=True))
        self.assertEqual(m.storage.get_meta("chunker_version"), "1")
        # Add a second file; index is now non-empty before sync, so the stamp
        # must stay whatever it was (not unset, not blindly rewritten).
        with open(os.path.join(ws, "knowledge", "infra", "b.md"), "w",
                  encoding="utf-8") as f:
            f.write("# B\n\n其他内容。" * 300)
        asyncio.run(m.sync())
        self.assertEqual(m.storage.get_meta("chunker_version"), "1")

    def test_sync_indexes_shared_knowledge_outside_agent_workspace(self):
        shared_root = Path(tempfile.mkdtemp())
        agent_workspace = Path(tempfile.mkdtemp())
        knowledge_dir = shared_root / "knowledge"
        knowledge_dir.mkdir()
        knowledge_file = knowledge_dir / "nested" / "index.md"
        knowledge_file.parent.mkdir()
        knowledge_file.write_text(
            "# Shared knowledge\n\nThe shared path is valid.\n",
            encoding="utf-8",
        )
        manager = self._make(str(agent_workspace))

        try:
            with patch(
                "common.state_dir.knowledge_dir", return_value=knowledge_dir
            ):
                asyncio.run(manager.sync())
                asyncio.run(manager.sync())

            expected_path = str(Path("knowledge") / "nested" / "index.md")
            expected_hash = MemoryStorage.compute_hash(
                knowledge_file.read_text(encoding="utf-8")
            )
            self.assertEqual(manager.storage.get_file_hash(expected_path), expected_hash)
            self.assertEqual(manager.storage.get_stats()["files"], 1)
            rows = manager.storage.conn.execute(
                "SELECT path, source FROM chunks"
            ).fetchall()
            self.assertTrue(rows)
            self.assertEqual(
                {(row["path"], row["source"]) for row in rows},
                {(expected_path, "knowledge")},
            )
        finally:
            manager.close()


if __name__ == "__main__":
    unittest.main()
