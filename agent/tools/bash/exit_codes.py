"""Exit-code semantics for shell commands.

A non-zero exit does not mean failure for every command: grep exits 1 when it
matched nothing, find exits 1 when a directory was unreadable, diff exits 1
when files differ. Reporting those as tool failures both misleads the model
and feeds the consecutive-failure circuit breaker.
"""

from typing import Optional, Tuple

# base command -> (exit code that is informational, what it means)
_SOFT_EXIT_1 = {
    "grep": "No matches found",
    "egrep": "No matches found",
    "fgrep": "No matches found",
    "rg": "No matches found",
    "ag": "No matches found",
    "find": "Some directories were inaccessible",
    "diff": "Files differ",
    "cmp": "Files differ",
    "test": "Condition is false",
    "[": "Condition is false",
}

_SEPARATORS = (";", "&&", "||", "|", "\n")


def _last_segment(command: str) -> Tuple[str, bool]:
    """Return the last segment and whether conditionals may have skipped it."""
    segment_start = 0
    conditional = False
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        for separator in _SEPARATORS:
            if command.startswith(separator, index):
                if separator in (";", "\n") and not command[index + len(separator):].strip():
                    return command[segment_start:index], conditional
                segment_start = index + len(separator)
                if separator in ("&&", "||"):
                    conditional = True
                elif separator in (";", "\n"):
                    conditional = False
                index += len(separator)
                break
        else:
            index += 1
    return command[segment_start:], conditional


def _base_command(segment: str) -> str:
    """First word of a segment, ignoring subshell parens and VAR=x prefixes."""
    for token in segment.strip().lstrip("({ \t").split():
        if "=" in token and not token.startswith("="):
            continue  # environment assignment, the command comes after
        return token
    return ""


def interpret(command: str, exit_code: int) -> Tuple[bool, Optional[str]]:
    """Decide whether an exit code is a real failure.

    Returns (is_error, note); note explains an informational non-zero exit.
    """
    if exit_code == 0:
        return False, None
    if exit_code == 1:
        segment, conditional = _last_segment(command)
        # A short-circuited chain can return an earlier command's failure.
        # Without execution provenance, do not invent the final command's
        # informational result. Unconditional lists and pipelines still use
        # their final command as before.
        meaning = None if conditional else _SOFT_EXIT_1.get(_base_command(segment))
        if meaning:
            return False, meaning
    return True, None
