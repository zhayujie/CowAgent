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
    
    def __init__(self, found: bool, index: int = -1, match_length: int = 0, content_for_replacement: str = ""):
        self.found = found
        self.index = index
        self.match_length = match_length
        self.content_for_replacement = content_for_replacement


def fuzzy_find_text(content: str, old_text: str) -> FuzzyMatchResult:
    """
    Find text in content, try exact match first, then fuzzy match
    
    :param content: Content to search in
    :param old_text: Text to find
    :return: Match result
    """
    # First try exact match
    index = content.find(old_text)
    if index != -1:
        return FuzzyMatchResult(
            found=True,
            index=index,
            match_length=len(old_text),
            content_for_replacement=content
        )
    
    # Try fuzzy match
    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old_text = normalize_for_fuzzy_match(old_text)
    
    index = fuzzy_content.find(fuzzy_old_text)
    if index != -1:
        # Fuzzy match successful, use normalized content for replacement
        return FuzzyMatchResult(
            found=True,
            index=index,
            match_length=len(fuzzy_old_text),
            content_for_replacement=fuzzy_content
        )
    
    # Not found
    return FuzzyMatchResult(found=False)


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
