"""A large knowledge index or workspace file must not cost the Agent its history.

- index.md past a size is injected as titles only, then cut, and the prompt says so
- the root index.md / log.md are left out of the vector index
- MEMORY.md past the byte cap keeps its newest entries, not just the hint
- a system prompt that alone fills the budget still keeps the previous turn
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agent.prompt.builder import (
    _INDEX_FULL_CHARS,
    _INDEX_MAX_CHARS,
    _build_knowledge_section,
    _compact_knowledge_index,
)
from agent.prompt.workspace import (
    _MEMORY_MAX_BYTES,
    _MEMORY_MAX_LINES,
    _truncate_memory_content,
)
from agent.protocol.agent_stream import AgentStreamExecutor


def _index(categories=3, per_category=300, summary_len=1100, title="Title"):
    lines = ["# Knowledge Index", ""]
    for c in range(categories):
        lines += [f"## Cat {c}", ""]
        for i in range(per_category):
            lines.append(f"- [{title} {c}-{i}](cat{c}/p{i}.md) — {'x' * summary_len}")
    return "\n".join(lines)


class TestCompactKnowledgeIndex(unittest.TestCase):
    def test_a_small_index_is_injected_as_is(self):
        content = "# Knowledge Index\n\n## A\n- [T](a/t.md) — short summary"
        text, omitted, compacted = _compact_knowledge_index(content)
        self.assertEqual(text, content)
        self.assertEqual(omitted, 0)
        self.assertFalse(compacted)

    def test_a_large_index_keeps_every_title_and_drops_the_summaries(self):
        text, omitted, compacted = _compact_knowledge_index(_index(per_category=20))
        self.assertTrue(compacted)
        self.assertEqual(omitted, 0)
        self.assertNotIn("xxxx", text)
        self.assertIn("## Cat 2", text)
        self.assertIn("- [Title 2-19](cat2/p19.md)", text)

    def test_titles_past_the_cap_are_counted_not_injected(self):
        content = _index(per_category=400, summary_len=10, title="T" * 80)
        text, omitted, compacted = _compact_knowledge_index(content)
        self.assertTrue(compacted)
        self.assertLessEqual(len(text), _INDEX_MAX_CHARS)
        self.assertGreater(omitted, 0)
        listed = text.count("\n- [")
        self.assertEqual(listed + omitted, 1200)

    def test_the_prompt_points_at_the_full_index_when_compacted(self):
        with _knowledge_dir(_index(per_category=20)) as ws:
            prompt = "\n".join(_build_knowledge_section(ws, "zh"))
        self.assertIn("索引较大，此处只列出标题", prompt)
        self.assertIn("index.md", prompt)
        self.assertNotIn("xxxx", prompt)

    def test_the_prompt_is_unchanged_for_a_small_index(self):
        content = "# Knowledge Index\n\n## A\n- [T](a/t.md) — short summary"
        self.assertLess(len(content), _INDEX_FULL_CHARS)
        with _knowledge_dir(content) as ws:
            prompt = "\n".join(_build_knowledge_section(ws, "en"))
        self.assertIn("- [T](a/t.md) — short summary", prompt)
        self.assertNotIn("only titles are listed", prompt)


class _knowledge_dir:
    def __init__(self, index_content):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.path = self._tmp.name
        kb = Path(self.path) / "knowledge"
        kb.mkdir()
        (kb / "index.md").write_text(index_content, encoding="utf-8")

    def __enter__(self):
        from unittest.mock import patch
        from common import state_dir
        self._patch = patch.object(
            state_dir, "knowledge_dir", lambda base=None: Path(self.path) / "knowledge"
        )
        self._patch.start()
        return self.path

    def __exit__(self, *exc):
        self._patch.stop()
        self._tmp.cleanup()


class TestBookkeepingFilesAreNotEmbedded(unittest.TestCase):
    def test_root_index_and_log_are_skipped_but_pages_are_scanned(self):
        import tempfile
        from unittest.mock import patch
        from agent.memory.manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmp:
            kb = Path(tmp) / "knowledge"
            (kb / "notes").mkdir(parents=True)
            (kb / "index.md").write_text("index", encoding="utf-8")
            (kb / "log.md").write_text("log", encoding="utf-8")
            (kb / "notes" / "index.md").write_text("a real page", encoding="utf-8")
            (kb / "notes" / "page.md").write_text("another page", encoding="utf-8")

            mm = MemoryManager.__new__(MemoryManager)
            seen = []

            def fake_chunk(content):
                return []

            mm.chunker = MagicMock()
            mm.chunker.chunk_markdown.side_effect = fake_chunk
            mm.chunker.chunk_text.side_effect = fake_chunk
            mm.storage = MagicMock()
            mm.storage.get_file_hash.return_value = None
            mm.storage.list_paths.return_value = []
            mm.config = MagicMock()
            mm.config.get_workspace.return_value = tmp

            real_read = Path.read_text

            def spy_read(self, *a, **kw):
                seen.append(str(self.relative_to(tmp)))
                return real_read(self, *a, **kw)

            from common import state_dir
            with patch.object(state_dir, "knowledge_dir", lambda base=None: kb), \
                    patch.object(state_dir, "shared_root", lambda: Path(tmp)), \
                    patch.object(Path, "read_text", spy_read):
                import asyncio
                try:
                    asyncio.run(mm.sync())
                except Exception:
                    pass

        knowledge_reads = sorted(p for p in seen if p.startswith("knowledge"))
        self.assertEqual(knowledge_reads, ["knowledge/notes/index.md", "knowledge/notes/page.md"])


class _Agent:
    memory_manager = None
    _current_user_id = None
    max_context_tokens = 300000

    def _get_model_context_window(self):
        return 1000000

    def _get_output_reserve_tokens(self):
        return 200000

    def _estimate_message_tokens(self, msg):
        return 500000


def _msg(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


class TestSystemPromptFillingTheBudget(unittest.TestCase):
    def _executor(self, messages):
        ex = AgentStreamExecutor.__new__(AgentStreamExecutor)
        ex.agent = _Agent()
        ex.messages = messages
        ex.system_prompt = "huge"
        ex.max_context_turns = 50
        ex._truncate_historical_tool_results = lambda: None
        ex._estimate_turn_tokens = lambda turn: 1000
        return ex

    def test_the_previous_turn_survives_as_text(self):
        ex = self._executor([
            _msg("user", "pick A or B"),
            _msg("assistant", "A is safer, B is faster"),
            _msg("user", "B"),
        ])
        ex._trim_messages()
        texts = [m["content"][0]["text"] for m in ex.messages]
        self.assertIn("pick A or B", texts)
        self.assertIn("A is safer, B is faster", texts)
        self.assertEqual(texts[-1], "B")

    def test_older_turns_are_still_dropped(self):
        ex = self._executor([
            _msg("user", "first"), _msg("assistant", "one"),
            _msg("user", "second"), _msg("assistant", "two"),
            _msg("user", "third"),
        ])
        ex._trim_messages()
        texts = [m["content"][0]["text"] for m in ex.messages]
        self.assertNotIn("first", texts)
        self.assertEqual(texts, ["second", "two", "third"])


class TestMemoryFileTruncation(unittest.TestCase):
    """MEMORY.md is cut down to its newest entries, never down to the hint."""

    @staticmethod
    def _body(result):
        """What the model actually reads, with the hint line taken off."""
        return result.split("\n\n", 1)[1]

    def test_a_memory_file_over_the_byte_cap_keeps_its_newest_entries(self):
        # Over the 25 KB budget on bytes, under it on lines: only the byte cap
        # is in play, so nothing here is rescued by the line cap.
        content = "\n".join(f"entry {i:03d} " + "x" * 280 for i in range(100))
        self.assertGreater(len(content.encode("utf-8")), _MEMORY_MAX_BYTES)
        self.assertLessEqual(len(content.split("\n")), _MEMORY_MAX_LINES)

        result = _truncate_memory_content(content)

        body = self._body(result)
        self.assertLessEqual(len(body.encode("utf-8")), _MEMORY_MAX_BYTES)
        self.assertIn("entry 099", body)     # newest entries are what survives
        self.assertNotIn("entry 000", body)  # the oldest are the ones dropped
        self.assertIn("use `memory_search`", result)

    def test_a_memory_file_within_the_budget_is_untouched(self):
        content = "\n".join(f"entry {i}" for i in range(20))
        self.assertEqual(_truncate_memory_content(content), content)

    def test_the_line_cap_keeps_the_newest_lines(self):
        content = "\n".join(f"entry {i:03d}" for i in range(_MEMORY_MAX_LINES + 50))
        self.assertLess(len(content.encode("utf-8")), _MEMORY_MAX_BYTES)

        result = _truncate_memory_content(content)

        self.assertIn(f"entry {_MEMORY_MAX_LINES + 49:03d}", result)
        self.assertNotIn("entry 000", result)
        self.assertIn("older entries truncated", result)


if __name__ == "__main__":
    unittest.main()
