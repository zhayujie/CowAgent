"""Truncation metadata for oversized tool output.

`truncate_tail` relabelled a byte cut as `"lines"` whenever the kept output
happened to fill `max_lines`, so one over-long line reported
`truncated_by == "lines"` while also reporting `last_line_partial=True` and
`output_bytes == max_bytes`. Callers pick their notice off `truncated_by`
(agent/tools/bash/bash.py), so the model was told "showing lines X-Y" for
output that had actually been cut in the middle of a line.
"""

import pytest

from agent.tools.utils.truncate import DEFAULT_MAX_BYTES, truncate_tail


def test_a_partial_line_filling_max_lines_is_reported_as_byte_truncation():
    result = truncate_tail("first\n" + "x" * 300, max_lines=1, max_bytes=100)

    assert result.truncated_by == "bytes"
    assert result.last_line_partial is True
    assert result.output_lines == 1
    assert result.output_bytes == 100


def test_byte_limit_across_whole_lines_is_reported_as_byte_truncation():
    result = truncate_tail("ab\ncd\nef", max_lines=10, max_bytes=4)

    assert result.truncated_by == "bytes"
    assert result.last_line_partial is False
    assert result.output_lines == 1


def test_the_line_limit_is_still_reported_as_line_truncation():
    result = truncate_tail("\n".join(str(i) for i in range(10)), max_lines=3)

    assert result.truncated_by == "lines"
    assert result.last_line_partial is False
    assert result.output_lines == 3


def test_a_whole_line_filling_max_lines_is_reported_as_line_truncation():
    result = truncate_tail("first\nsecond", max_lines=1, max_bytes=100)

    assert result.truncated_by == "lines"
    assert result.last_line_partial is False
    assert result.content == "second"


@pytest.mark.parametrize("prefix", ["", "first\n"])
@pytest.mark.parametrize("character", ["x", "€"])
@pytest.mark.parametrize("max_lines", [1, 2000])
def test_oversized_last_line_with_trailing_newline_keeps_a_partial_tail(prefix, character, max_lines):
    line = character * (DEFAULT_MAX_BYTES + 1)
    result = truncate_tail(prefix + line + "\n", max_lines=max_lines)
    expected = character * (DEFAULT_MAX_BYTES // len(character.encode("utf-8")))

    assert result.content == expected
    assert result.truncated_by == "bytes"
    assert result.last_line_partial is True
    assert result.output_lines == 1
    assert result.output_bytes == len(expected.encode("utf-8"))


def test_whole_lines_with_trailing_newline_keep_existing_behavior():
    result = truncate_tail("first\nlast\n", max_bytes=5)

    assert result.content == "last\n"
    assert result.last_line_partial is False
    assert result.output_lines == 2

