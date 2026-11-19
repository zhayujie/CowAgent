from .truncate import (
    truncate_head,
    truncate_tail,
    truncate_line,
    format_size,
    TruncationResult,
    DEFAULT_MAX_LINES,
    DEFAULT_MAX_BYTES,
    GREP_MAX_LINE_LENGTH
)

from .diff import (
    strip_bom,
    detect_line_ending,
    normalize_to_lf,
    restore_line_endings,
    normalize_for_fuzzy_match,
    count_matches,
    find_match_spans,
    fuzzy_find_text,
    generate_diff_string,
    looks_like_line_numbered_block,
    reindent_replacement,
    strip_line_number_prefixes,
    trim_outer_newlines,
    FuzzyMatchResult
)

from .url_safety import (
    validate_url_safe,
    assert_public_ip
)

__all__ = [
    'truncate_head',
    'truncate_tail',
    'truncate_line',
    'format_size',
    'TruncationResult',
    'DEFAULT_MAX_LINES',
    'DEFAULT_MAX_BYTES',
    'GREP_MAX_LINE_LENGTH',
    'strip_bom',
    'detect_line_ending',
    'normalize_to_lf',
    'restore_line_endings',
    'normalize_for_fuzzy_match',
    'count_matches',
    'find_match_spans',
    'fuzzy_find_text',
    'generate_diff_string',
    'looks_like_line_numbered_block',
    'reindent_replacement',
    'trim_outer_newlines',
    'strip_line_number_prefixes',
    'FuzzyMatchResult',
    'validate_url_safe',
    'assert_public_ip'
]
