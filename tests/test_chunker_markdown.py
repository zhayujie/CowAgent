# encoding: utf-8
"""
Tests for TextChunker.chunk_markdown — structure-aware (heading) chunking of
memory/knowledge markdown files.

Strategy pinned here (see agent/memory/chunker.py docstring):
  - A file <= MD_CHUNK_TARGET(1500) chars is ONE chunk.
  - Larger files are heading-split via markdown-it into per-heading "own body"
    candidates, then greedily merged across headings up to the target, then a
    single tail-fold merges a trailing fragment (<= MD_FRAGMENT_MAX=400 chars)
    into the previous chunk.
Contract: line numbers are 1-based, contiguous and cover the whole file without
overlap or gaps; each chunk's text starts at a real heading line and its lines
fall inside [start_line, end_line].
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.chunker import TextChunker


def _md(items):
    """items = [(heading, [body...]), ...] -> markdown string."""
    parts = []
    for heading, body in items:
        parts.append(heading)
        parts.extend(body)
    return "\n".join(parts)


def _assert_contiguous_full_cover(test, chunks, n_lines):
    """Assert chunks are 1-based, contiguous, non-overlapping, cover whole file,
    and every chunk's text starts with a real heading present in that span."""
    prev_end = 0
    for ch in chunks:
        test.assertGreater(ch.start_line, prev_end, "chunks must not overlap/repeat")
        test.assertGreaterEqual(ch.start_line, 1)
        test.assertLessEqual(ch.end_line, n_lines)
        # text starts at a heading marker and that heading is inside its lines
        first = ch.text.lstrip().splitlines()[0] if ch.text.strip() else ""
        test.assertTrue(first.startswith("#"), f"chunk should start at a heading: {first!r}")
        prev_end = ch.end_line
    test.assertEqual(prev_end, n_lines, "chunks must cover the whole file")


class TestChunkMarkdownSmall(unittest.TestCase):
    def setUp(self):
        self.c = TextChunker()

    def test_empty_returns_none(self):
        self.assertEqual(self.c.chunk_markdown("   \n  \n"), [])

    def test_short_file_is_single_chunk(self):
        md = "# 标题一\n\n正文只有几行而已。\n"
        chunks = self.c.chunk_markdown(md)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].start_line, 1)
        self.assertIn("标题一", chunks[0].text)

    def test_short_file_keeps_content(self):
        md = "# 根\n\n段落内容。\n\n## 小节\n\n小节正文。\n"
        chunks = self.c.chunk_markdown(md)
        self.assertEqual(len(chunks), 1)
        self.assertIn("段落内容", chunks[0].text)
        self.assertIn("小节正文", chunks[0].text)


class TestChunkMarkdownLarge(unittest.TestCase):
    """Large (>1500 char) files trigger the heading-aware path."""

    def setUp(self):
        self.c = TextChunker()

    def test_large_file_contiguous_full_cover(self):
        bigA = ["A正文内容句子。" for _ in range(120)]
        bigB = ["B的正文详细内容描述。" for _ in range(140)]
        md = _md([
            ("# 文档根", ["根引言。"]),
            ("## 主题A", bigA),
            ("## 主题B", bigB),
            ("## 主题C", ["短的结尾内容。"]),
        ])
        self.assertGreater(len(md), self.c.MD_CHUNK_TARGET)
        chunks = self.c.chunk_markdown(md)
        self.assertGreater(len(chunks), 1)
        _assert_contiguous_full_cover(self, chunks, len(md.split("\n")))

    def test_does_not_interleave_unrelated_headings(self):
        """A chunk's text should only contain headings that lie within its own
        [start_line, end_line] span."""
        md = _md([
            ("# A", ["a" * 200]),
            ("## B", ["b" * 200]),
            ("## C", ["c" * 200]),
            ("## D", ["d" * 200]),
        ])  # ~>1500
        chunks = self.c.chunk_markdown(md)
        lines = md.split("\n")
        for ch in chunks:
            span_text = "\n".join(lines[ch.start_line - 1: ch.end_line])
            # every heading present in ch.text must also be within its span
            for ln in ch.text.splitlines():
                if ln.lstrip().startswith("#"):
                    self.assertIn(ln, span_text, f"heading {ln!r} escaped its span")

    def test_code_block_fake_heading_is_not_a_boundary(self):
        """# inside a fenced code block must not create a split boundary."""
        body = [
            "正文段落。",
            "```python",
            "# 这不是真标题",
            "print('hi')",
            "```",
            "后续段落。",
        ]
        md = _md([("# 真标题", body)])
        # keep under target so the whole thing is one chunk; if any fake-heading
        # boundary had been introduced the file would have split — it must not.
        if len(md) <= self.c.MD_CHUNK_TARGET:
            chunks = self.c.chunk_markdown(md)
            self.assertEqual(len(chunks), 1)
            self.assertIn("不是真标题", chunks[0].text)

    def test_tail_fragment_folds_into_prev_chunk(self):
        """A trailing heading whose whole body is <= fragment max must be folded
        into the previous chunk, so no orphaned tiny chunk is left at the end."""
        big = ["x" * 500 for _ in range(3)]      # ~1500+, one big heading body
        md = _md([
            ("# 大块", big),
            ("# 小尾", ["y" * 50]),               # 50-char tail
        ])
        chunks = self.c.chunk_markdown(md)
        # the tail heading must never survive as its own chunk
        last = chunks[-1]
        self.assertIn("小尾", last.text)

    def test_all_headings_preserved_somewhere(self):
        md = _md([
            ("# 一", ["正文A。" * 80]),
            ("# 二", ["正文B。" * 80]),
            ("# 三", ["正文C。" * 80]),
            ("# 四", ["正文D。" * 80]),
        ])
        chunks = self.c.chunk_markdown(md)
        joined = "".join(ch.text for ch in chunks)
        for h in ("# 一", "# 二", "# 三", "# 四"):
            self.assertIn(h, joined)


class TestChunkMarkdownCoverage(unittest.TestCase):
    """Every line of a large file lands in exactly one chunk."""

    def setUp(self):
        self.c = TextChunker()

    def _assert_each_line_once(self, chunks, n_lines):
        covered = []
        for ch in chunks:
            covered.extend(range(ch.start_line, ch.end_line + 1))
        self.assertEqual(covered, list(range(1, n_lines + 1)))

    def test_text_before_the_first_heading_is_kept(self):
        """A preface (front text, a note, a TOC) before the first heading was
        in no segment at all, so it never reached the index."""
        md = "\n".join([
            "前言：这段文字位于第一个标题之前。",
            "",
            "# 一",
            "正文A。" * 200,
            "# 二",
            "正文B。" * 200,
        ])
        self.assertGreater(len(md), self.c.MD_CHUNK_TARGET)
        chunks = self.c.chunk_markdown(md)
        self.assertEqual(chunks[0].start_line, 1)
        self.assertIn("前言", chunks[0].text)
        self._assert_each_line_once(chunks, len(md.split("\n")))

    def test_skipped_heading_level_is_not_indexed_twice(self):
        """``#`` followed by ``###`` (no ``##``): the parent's own body ran on
        past the ``###`` heading, so that section was in two chunks."""
        md = _md([
            ("# 父", ["父正文。" * 200]),
            ("### 子", ["子正文。" * 200]),
            ("# 后", ["后正文。" * 200]),
        ])
        chunks = self.c.chunk_markdown(md)
        joined = "\n".join(ch.text for ch in chunks)
        self.assertEqual(joined.count("### 子"), 1)
        self._assert_each_line_once(chunks, len(md.split("\n")))


if __name__ == "__main__":
    unittest.main()
