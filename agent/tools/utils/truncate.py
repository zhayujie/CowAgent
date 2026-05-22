"""
Shared truncation utilities for tool outputs.

Truncation is based on two independent limits - whichever is hit first wins:
- Line limit (default: 2000 lines)
- Byte limit (default: 50KB)

Never returns partial lines (except bash tail truncation edge case).
"""

from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Literal


DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024  # 50KB
GREP_MAX_LINE_LENGTH = 500  # Max chars per grep match line


class TruncationResult:
    """Truncation result"""
    
    def __init__(
        self,
        content: str,
        truncated: bool,
        truncated_by: Optional[Literal["lines", "bytes"]],
        total_lines: int,
        total_bytes: int,
        output_lines: int,
        output_bytes: int,
        last_line_partial: bool = False,
        first_line_exceeds_limit: bool = False,
        max_lines: int = DEFAULT_MAX_LINES,
        max_bytes: int = DEFAULT_MAX_BYTES
    ):
        self.content = content
        self.truncated = truncated
        self.truncated_by = truncated_by
        self.total_lines = total_lines
        self.total_bytes = total_bytes
        self.output_lines = output_lines
        self.output_bytes = output_bytes
        self.last_line_partial = last_line_partial
        self.first_line_exceeds_limit = first_line_exceeds_limit
        self.max_lines = max_lines
        self.max_bytes = max_bytes
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "content": self.content,
            "truncated": self.truncated,
            "truncated_by": self.truncated_by,
            "total_lines": self.total_lines,
            "total_bytes": self.total_bytes,
            "output_lines": self.output_lines,
            "output_bytes": self.output_bytes,
            "last_line_partial": self.last_line_partial,
            "first_line_exceeds_limit": self.first_line_exceeds_limit,
            "max_lines": self.max_lines,
            "max_bytes": self.max_bytes
        }


def format_size(bytes_count: int) -> str:
    """Format bytes as human-readable size"""
    if bytes_count < 1024:
        return f"{bytes_count}B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f}KB"
    else:
        return f"{bytes_count / (1024 * 1024):.1f}MB"


def truncate_head(content: str, max_lines: Optional[int] = None, max_bytes: Optional[int] = None) -> TruncationResult:
    """
    Truncate content from the head (keep first N lines/bytes).
    Suitable for file reads where you want to see the beginning.
    
    Never returns partial lines. If first line exceeds byte limit,
    returns empty content with first_line_exceeds_limit=True.
    
    :param content: Content to truncate
    :param max_lines: Maximum number of lines (default: 2000)
    :param max_bytes: Maximum number of bytes (default: 50KB)
    :return: Truncation result
    """
    if max_lines is None:
        max_lines = DEFAULT_MAX_LINES
    if max_bytes is None:
        max_bytes = DEFAULT_MAX_BYTES
    
    total_bytes = len(content.encode('utf-8'))
    lines = content.split('\n')
    total_lines = len(lines)
    
    # Check if no truncation is needed
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            last_line_partial=False,
            first_line_exceeds_limit=False,
            max_lines=max_lines,
            max_bytes=max_bytes
        )
    
    # Check if first line alone exceeds byte limit
    first_line_bytes = len(lines[0].encode('utf-8'))
    if first_line_bytes > max_bytes:
        return TruncationResult(
            content="",
            truncated=True,
            truncated_by="bytes",
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=0,
            output_bytes=0,
            last_line_partial=False,
            first_line_exceeds_limit=True,
            max_lines=max_lines,
            max_bytes=max_bytes
        )
    
    # Collect complete lines that fit
    output_lines_arr = []
    output_bytes_count = 0
    truncated_by = "lines"
    
    for i, line in enumerate(lines):
        if i >= max_lines:
            break
        
        # Calculate line bytes (add 1 for newline if not first line)
        line_bytes = len(line.encode('utf-8')) + (1 if i > 0 else 0)
        
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        
        output_lines_arr.append(line)
        output_bytes_count += line_bytes
    
    # If exited due to line limit
    if len(output_lines_arr) >= max_lines and output_bytes_count <= max_bytes:
        truncated_by = "lines"
    
    output_content = '\n'.join(output_lines_arr)
    final_output_bytes = len(output_content.encode('utf-8'))
    
    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        last_line_partial=False,
        first_line_exceeds_limit=False,
        max_lines=max_lines,
        max_bytes=max_bytes
    )


def truncate_tail(content: str, max_lines: Optional[int] = None, max_bytes: Optional[int] = None) -> TruncationResult:
    """
    Truncate content from tail (keep last N lines/bytes).
    Suitable for bash output where you want to see the ending content (errors, final results).
    
    If the last line of original content exceeds byte limit, may return partial first line.
    
    :param content: Content to truncate
    :param max_lines: Maximum lines (default: 2000)
    :param max_bytes: Maximum bytes (default: 50KB)
    :return: Truncation result
    """
    if max_lines is None:
        max_lines = DEFAULT_MAX_LINES
    if max_bytes is None:
        max_bytes = DEFAULT_MAX_BYTES
    
    total_bytes = len(content.encode('utf-8'))
    lines = content.split('\n')
    total_lines = len(lines)
    
    # Check if no truncation is needed
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            last_line_partial=False,
            first_line_exceeds_limit=False,
            max_lines=max_lines,
            max_bytes=max_bytes
        )
    
    # Work backwards from the end
    output_lines_arr = []
    output_bytes_count = 0
    truncated_by = "lines"
    last_line_partial = False
    
    for i in range(len(lines) - 1, -1, -1):
        if len(output_lines_arr) >= max_lines:
            break
        
        line = lines[i]
        # Calculate line bytes (add newline if not the first added line)
        line_bytes = len(line.encode('utf-8')) + (1 if len(output_lines_arr) > 0 else 0)
        
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            # Edge case: if we haven't added any lines yet and this line exceeds maxBytes,
            # take the end portion of this line
            if len(output_lines_arr) == 0:
                truncated_line = _truncate_string_to_bytes_from_end(line, max_bytes)
                output_lines_arr.insert(0, truncated_line)
                output_bytes_count = len(truncated_line.encode('utf-8'))
                last_line_partial = True
            break
        
        output_lines_arr.insert(0, line)
        output_bytes_count += line_bytes
    
    # If exited due to line limit
    if len(output_lines_arr) >= max_lines and output_bytes_count <= max_bytes:
        truncated_by = "lines"
    
    output_content = '\n'.join(output_lines_arr)
    final_output_bytes = len(output_content.encode('utf-8'))
    
    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        last_line_partial=last_line_partial,
        first_line_exceeds_limit=False,
        max_lines=max_lines,
        max_bytes=max_bytes
    )


def _truncate_string_to_bytes_from_end(text: str, max_bytes: int) -> str:
    """
    Truncate string to fit byte limit (from end).
    Properly handles multi-byte UTF-8 characters.
    
    :param text: String to truncate
    :param max_bytes: Maximum bytes
    :return: Truncated string
    """
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    
    # Start from end, skip back maxBytes
    start = len(encoded) - max_bytes
    
    # Find valid UTF-8 boundary (character start)
    while start < len(encoded) and (encoded[start] & 0xC0) == 0x80:
        start += 1
    
    return encoded[start:].decode('utf-8', errors='ignore')


def truncate_line(line: str, max_chars: int = GREP_MAX_LINE_LENGTH) -> Tuple[str, bool]:
    """
    Truncate single line to max characters, add [truncated] suffix.
    Used for grep match lines.
    
    :param line: Line to truncate
    :param max_chars: Maximum characters
    :return: (truncated text, whether truncated)
    """
    if len(line) <= max_chars:
        return line, False
    return f"{line[:max_chars]}... [truncated]", True
