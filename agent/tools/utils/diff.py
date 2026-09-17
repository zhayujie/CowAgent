"""
Diff tools for file editing
Provides fuzzy matching and diff generation functionality
"""

import difflib
import re
from typing import Optional, Tuple


def strip_bom(text: str) -> Tuple[str, str]:
    """
    Remove BOM (Byte Order Mark)

    :param text: Original text
    :return: (BOM, text after removing BOM)
    """
    if text.startswith('\ufeff'):
        return '\ufeff', text[1:]
    return '', text


def detect_line_ending(text: str) -> str:
    """
    Detect line ending type

    :param text: Text content
    :return: Line ending type ('\r\n' or '\n')
    """
    if '\r\n' in text:
        return '\r\n'
    return '\n'


def normalize_to_lf(text: str) -> str:
    """
    Normalize all line endings to LF (\n)

    :param text: Original text
    :return: Normalized text
    """
    return text.replace('\r\n', '\n').replace('\r', '\n')


def restore_line_endings(text: str, original_ending: str) -> str:
    """
    Restore original line endings

    :param text: LF normalized text
    :param original_ending: Original line ending
    :return: Text with restored line endings
    """
    if original_ending == '\r\n':
        return text.replace('\n', '\r\n')
    return text


def normalize_for_fuzzy_match(text: str) -> str:
    """
    Normalize text for fuzzy matching
    Remove excess whitespace but preserve basic structure

    :param text: Original text
    :return: Normalized text
    """
    # Compress multiple spaces to one
    text = re.sub(r'[ \t]+', ' ', text)
    # Remove trailing spaces
    text = re.sub(r' +\n', '\n', text)
    # Remove leading spaces (but preserve indentation structure, only remove excess)
    lines = text.split('\n')
    normalized_lines = []
    for line in lines:
        # Preserve indentation but normalize to multiples of single spaces
        stripped = line.lstrip()
        if stripped:
            indent_count = len(line) - len(stripped)
            # Normalize indentation (convert tabs to spaces)
            normalized_indent = ' ' * indent_count
            normalized_lines.append(normalized_indent + stripped)
        else:
            normalized_lines.append('')
    return '\n'.join(normalized_lines)


class FuzzyMatchResult:
    """Fuzzy match result"""

    def __init__(self, found: bool, index: int = -1, match_length: int = 0,
                 content_for_replacement: str = "", exact: bool = False):
        self.found = found
        self.index = index
        self.match_length = match_length
        self.content_for_replacement = content_for_replacement
        # False when the whitespace-flexible pattern was needed. The caller must
        # then re-anchor the replacement's indentation (see reindent_replacement).
        self.exact = exact


def _build_fuzzy_pattern(old_text: str) -> Optional[str]:
    """
    Build the whitespace-flexible regex used to locate ``old_text`` fuzzily.

    Returns ``None`` when ``old_text`` has no non-whitespace content to match.
    This is the single source of truth for fuzzy matching, so that *finding* a
    match (:func:`fuzzy_find_text`) and *counting* occurrences
    (:func:`count_matches`) always use the exact same rules.
    """
    stripped = old_text.strip('\n')
    if not stripped.strip():
        return None

    source_lines = stripped.split('\n')
    line_patterns = []
    for i, line in enumerate(source_lines):
        tokens = line.split()
        if not tokens:
            line_patterns.append(r'[ \t]*')
            continue
        # Tolerate any run of blanks between tokens.
        core = r'[ \t]+'.join(re.escape(tok) for tok in tokens)
        # First-line leading whitespace is folded into the match only when
        # old_text itself was indented here; otherwise it stays OUTSIDE the
        # match so a no-indent old_text preserves (does not swallow and drop)
        # the file's existing indentation -- mirroring an exact substring
        # match. Inner lines always tolerate indentation: it sits inside the
        # matched region and is re-supplied by new_text.
        if i > 0 or line[:1] in (' ', '\t'):
            core = r'[ \t]*' + core
        line_patterns.append(core + r'[ \t]*')
    return '\n'.join(line_patterns)


def find_match_spans(content: str, old_text: str) -> Tuple[list, bool]:
    """
    Locate every non-overlapping occurrence of ``old_text`` in ``content``.

    Exact substring matching is preferred; only when it finds nothing do we fall
    back to the whitespace-flexible pattern. Finding, counting and replacing all
    go through this one function so the uniqueness guard can never disagree with
    what actually gets replaced.

    :return: (list of (start, end) offsets into ``content``, whether exact)
    """
    if not old_text:
        return [], True

    if content.find(old_text) != -1:
        spans = []
        start = 0
        while True:
            index = content.find(old_text, start)
            if index == -1:
                break
            spans.append((index, index + len(old_text)))
            start = index + len(old_text)
        return spans, True

    # The exact substring was not found, most likely because the whitespace
    # differs (indentation, spaces around operators, trailing spaces). Locate
    # the region in the ORIGINAL content using a whitespace-flexible pattern
    # and return offsets into that original content.
    #
    # This must NOT replace inside a whitespace-normalized copy of the file:
    # doing so previously returned the normalized copy as the replacement base,
    # which rewrote the whole file with collapsed indentation.
    pattern = _build_fuzzy_pattern(old_text)
    if pattern is None:
        return [], False
    return [(m.start(), m.end()) for m in re.finditer(pattern, content)], False


def fuzzy_find_text(content: str, old_text: str) -> FuzzyMatchResult:
    """Find the first occurrence of ``old_text``; exact match preferred."""
    spans, exact = find_match_spans(content, old_text)
    if not spans:
        return FuzzyMatchResult(found=False)
    start, end = spans[0]
    return FuzzyMatchResult(
        found=True,
        index=start,
        match_length=end - start,
        content_for_replacement=content,
        exact=exact,
    )


def count_matches(content: str, old_text: str) -> int:
    """Count occurrences using the same strategy as :func:`find_match_spans`."""
    return len(find_match_spans(content, old_text)[0])


def reindent_replacement(matched_text: str, old_text: str, new_text: str) -> str:
    """
    Re-anchor ``new_text``'s indentation to the indentation actually in the file.

    The fuzzy pattern tolerates differing indentation, and when ``old_text`` is
    indented that leading whitespace sits *inside* the matched region. Writing
    ``new_text`` back verbatim would therefore silently reindent the line to
    whatever the model happened to send - in Python or YAML that changes the
    meaning of the code, or breaks it outright, while the tool reports success.

    Only the first line's indentation is compared; the delta is applied to every
    line so the block's internal structure is preserved.
    """
    old_first = old_text.split('\n', 1)[0]
    old_indent = old_first[:len(old_first) - len(old_first.lstrip())]
    if not old_indent:
        # An unindented old_text never swallows the file's indentation, so
        # there is nothing to restore.
        return new_text

    file_first = matched_text.split('\n', 1)[0]
    file_indent = file_first[:len(file_first) - len(file_first.lstrip())]
    if file_indent == old_indent:
        return new_text

    out = []
    for line in new_text.split('\n'):
        if line.strip() and line.startswith(old_indent):
            out.append(file_indent + line[len(old_indent):])
        else:
            out.append(line)
    return '\n'.join(out)


# A `12|` gutter, as emitted by the read tool.
_LINE_NUMBER_PREFIX_RE = re.compile(r'^[ \t]*\d+\|')


def looks_like_line_numbered_block(text: str) -> bool:
    """
    Detect read-tool display text (``12|content``) being written back as file content.

    Since read numbers its output, a model that echoes that output into write -
    or into edit's newText - would silently prepend a gutter to every line of a
    real file. Rejecting is only safe if legitimate content is never mistaken
    for a gutter, so this demands three things at once: at least two lines, a
    clear majority carrying a numeric prefix, and those numbers running
    consecutively. A lone ``1|value`` line, a markdown table row or an ordinary
    numbered list therefore all pass through untouched.
    """
    if not isinstance(text, str):
        return False

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    numbered = []
    for line in lines:
        prefix, sep, _rest = line.lstrip().partition('|')
        if sep and prefix.isdigit():
            numbered.append(int(prefix))

    if len(numbered) < 2 or len(numbered) / len(lines) < 0.6:
        return False
    return all(b == a + 1 for a, b in zip(numbered, numbered[1:]))


def strip_line_number_prefixes(text: str) -> Optional[str]:
    """
    Remove ``12|`` gutters the model may have copied out of read output.

    Returns None when the text does not look like numbered output, so callers
    only use this as a fallback after normal matching failed - that way content
    which genuinely contains ``12|`` is never corrupted.
    """
    lines = text.split('\n')
    numbered = [line for line in lines if line.strip()]
    if not numbered or not all(_LINE_NUMBER_PREFIX_RE.match(l) for l in numbered):
        return None
    stripped = '\n'.join(
        _LINE_NUMBER_PREFIX_RE.sub('', line, count=1) if line.strip() else line
        for line in lines
    )
    return stripped if stripped != text else None


def generate_diff_string(old_content: str, new_content: str) -> dict:
    """
    Generate unified diff string

    :param old_content: Old content
    :param new_content: New content
    :return: Dictionary containing diff and first changed line number
    """
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')

    # Generate unified diff
    diff_lines = list(difflib.unified_diff(
        old_lines,
        new_lines,
        lineterm='',
        fromfile='original',
        tofile='modified'
    ))

    # Find first changed line number
    first_changed_line = None
    for line in diff_lines:
        if line.startswith('@@'):
            # Parse @@ -1,3 +1,3 @@ format
            match = re.search(r'@@ -\d+,?\d* \+(\d+)', line)
            if match:
                first_changed_line = int(match.group(1))
                break

    diff_string = '\n'.join(diff_lines)

    return {
        'diff': diff_string,
        'first_changed_line': first_changed_line
    }
