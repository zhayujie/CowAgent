"""Memory chunk line ranges should not invent a line after a trailing newline.

The chunker split file contents on "\\n", so a note ending in a newline was
numbered one line too long. memory_search then advertised that phantom line,
which disagrees with memory_get after it started dropping the trailing empty
element (see test_memory_get_trailing_newline.py).
"""

from agent.memory.chunker import TextChunker


def _split_lines(content: str) -> list:
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def test_chunk_text_does_not_count_a_phantom_line_after_a_trailing_newline():
    chunker = TextChunker()
    chunks = chunker.chunk_text("hello\nworld\n")

    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2
    assert chunks[0].text == "hello\nworld"


def test_chunk_text_without_a_trailing_newline_is_unchanged():
    chunker = TextChunker()
    chunks = chunker.chunk_text("hello\nworld")

    assert [(c.start_line, c.end_line, c.text) for c in chunks] == [
        (1, 2, "hello\nworld")
    ]


def test_chunk_text_keeps_a_real_blank_line_before_the_final_newline():
    chunker = TextChunker()
    chunks = chunker.chunk_text("hello\n\n")

    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2
    # join(["hello", ""]) yields "hello\n"; end_line still reports both lines.
    assert chunks[0].text == "hello\n"


def test_chunk_markdown_short_file_matches_real_line_count():
    chunker = TextChunker()
    text = "# Title\n\nA short memory note.\n"
    chunks = chunker.chunk_markdown(text)

    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == len(_split_lines(text)) == 3
    assert chunks[0].text == text


def test_chunk_markdown_large_file_cover_stops_at_real_lines():
    chunker = TextChunker()
    body_a = "A content sentence.\n" * 80
    body_b = "B content sentence.\n" * 80
    text = f"# Topic A\n\n{body_a}\n# Topic B\n\n{body_b}"
    assert len(text) > chunker.MD_CHUNK_TARGET
    chunks = chunker.chunk_markdown(text)
    assert len(chunks) >= 1

    n_lines = len(_split_lines(text))
    covered = []
    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= n_lines
        covered.extend(range(chunk.start_line, chunk.end_line + 1))
    assert covered == list(range(1, n_lines + 1))
