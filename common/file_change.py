"""Extract the structured diff from a successful file-tool result."""

import json


MAX_FILE_CHANGE_DIFF_CHARS = 64 * 1024


def file_change_from_result(tool_name, result):
    """Return display-safe shape, or None for non-file/legacy tool results."""
    if tool_name not in {"edit", "write"}:
        return None
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            return None
    if not isinstance(result, dict):
        return None
    path, diff = result.get("path"), result.get("diff")
    if not isinstance(path, str) or not path or not isinstance(diff, str) or not diff:
        return None
    first_line = result.get("first_changed_line")
    truncated = len(diff) > MAX_FILE_CHANGE_DIFF_CHARS
    if truncated:
        line_end = diff.rfind("\n", 0, MAX_FILE_CHANGE_DIFF_CHARS)
        diff = diff[:line_end if line_end > 0 else MAX_FILE_CHANGE_DIFF_CHARS]
    return {
        "path": path[:4096],
        "diff": diff,
        "first_changed_line": first_line if isinstance(first_line, int) else None,
        "truncated": truncated,
    }
