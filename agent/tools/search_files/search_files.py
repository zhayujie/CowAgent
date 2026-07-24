"""
SearchFiles tool - search file contents across the workspace (grep-like)
"""

import fnmatch
import os
import time
from typing import Dict, Any, List, Tuple

import regex as re  # not stdlib re: .search() takes a real per-call timeout, stdlib re has none

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.truncate import truncate_line
from common.utils import expand_path

DEFAULT_MAX_RESULTS = 50
MAX_RESULTS_CAP = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
SEARCH_TIMEOUT_SECONDS = 30
REGEX_MATCH_TIMEOUT_SECONDS = 1  # caps one regex.search() call; SEARCH_TIMEOUT_SECONDS is the separate overall-walk deadline

# Matches read.py's issue #2913 fix: /proc/<pid|self|thread-self>/environ
# mirrors any secrets loaded into the process environment from ~/.cow/.env.
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

# No `rg` in the Docker image or installers, so this walks pure Python with
# no .gitignore awareness — a conservative hardcoded denylist, not the same
# thing as `rg`'s .gitignore-driven skipping.
_SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
    "target", "vendor", ".tox", "coverage", ".idea",
}


class SearchFiles(BaseTool):
    """Tool for searching file contents by pattern across a directory tree."""

    name: str = "search_files"
    description: str = (
        "Search file contents for a text/regex pattern across a directory tree. "
        "Returns matching lines with file path and line number. Prefer this over "
        "`bash` + grep for content search: no shell execution, structured output, "
        "automatic binary/oversized-file skipping."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Text or regex pattern to search for."
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: workspace root). Relative paths are based on workspace directory."
            },
            "file_glob": {
                "type": "string",
                "description": "Glob to filter which files are searched, e.g. '*.py' (default: all files)."
            },
            "max_results": {
                "type": "integer",
                "description": f"Maximum number of matches to return (default: {DEFAULT_MAX_RESULTS}, capped at {MAX_RESULTS_CAP})."
            }
        },
        "required": ["pattern"]
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.timeout = self.config.get("timeout", SEARCH_TIMEOUT_SECONDS)
        # Resolved once (assumes ~/.cow is stable for this session), not per-check.
        self._cow_dir = os.path.realpath(expand_path("~/.cow")).replace(os.sep, "/")

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute a content search.

        :param args: pattern (required), path/file_glob/max_results (optional)
        :return: ToolResult with {matches: [{file, line, match}, ...], match_count, notice?}
        """
        pattern = args.get("pattern", "")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.fail("Error: pattern parameter is required")

        path = args.get("path", ".") or "."
        file_glob = args.get("file_glob", "*") or "*"
        if not isinstance(file_glob, str):
            return ToolResult.fail(f"Error: file_glob must be a string, got: {file_glob!r}")
        max_results = args.get("max_results", DEFAULT_MAX_RESULTS)
        if isinstance(max_results, float) and not max_results.is_integer():
            return ToolResult.fail(f"Error: max_results must be an integer, got: {max_results!r}")
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            return ToolResult.fail(f"Error: max_results must be an integer, got: {max_results!r}")
        if max_results <= 0:
            return ToolResult.fail("Error: max_results must be a positive integer")
        max_results = min(max_results, MAX_RESULTS_CAP)

        try:
            compiled_pattern = re.compile(pattern)
        except re.error as e:
            return ToolResult.fail(f"Error: invalid regex pattern: {e}")

        root = self._resolve_path(path)
        if self._is_credential_path(root):
            return ToolResult.fail(
                "Error: Access denied. API keys and credentials must be accessed through the env_config tool only."
            )
        if not os.path.exists(root):
            return ToolResult.fail(
                f"Error: path not found: {path}\nResolved to: {root}\n"
                f"Hint: Relative paths are based on workspace ({self.cwd}). For directories outside workspace, use absolute paths."
            )
        if not os.path.isdir(root):
            return ToolResult.fail(f"Error: path is not a directory: {path}")

        matches, timed_out, pattern_timeout, skip_list_pruned = self._search(compiled_pattern, root, file_glob, max_results)

        payload = {"matches": matches, "match_count": len(matches)}
        notices = []
        if len(matches) >= max_results:
            if max_results >= MAX_RESULTS_CAP:
                # A max_results*2 suggestion here would just echo the same capped number.
                notices.append(f"{max_results} result limit reached (hard maximum). Narrow `path` or `file_glob` to see more.")
            else:
                # Fires even if the true match count exactly equals max_results
                # (nothing more actually exists) — matches ls.py's identical
                # entry_limit_reached imprecision, not fixed here either.
                notices.append(
                    f"{max_results} result limit reached. "
                    f"Use max_results={min(max_results * 2, MAX_RESULTS_CAP)} to see more."
                )
        if timed_out:
            notices.append(
                f"Search stopped after {self.timeout}s — results may be incomplete. "
                f"Narrow `path` or `file_glob` to search a smaller tree."
            )
        if pattern_timeout:
            notices.append(
                f"Pattern took longer than {REGEX_MATCH_TIMEOUT_SECONDS}s to match on a line in one "
                f"or more files — the rest of that file's content was not searched. Results may be "
                f"incomplete. Simplify `pattern` to avoid catastrophic backtracking."
            )
        if skip_list_pruned:
            notices.append(
                "Some directories were excluded by a fixed skip-list (e.g. .git, node_modules, "
                "dist, vendor) — match_count does not reflect their contents."
            )
        if notices:
            # Must live in `result`, not `ToolResult.ext_data` — `_execute_tool`
            # never forwards `ext_data` to the model.
            payload["notice"] = " ".join(notices)
        return ToolResult.success(payload)

    def _resolve_path(self, path: str) -> str:
        """Resolve path to absolute path (same convention as read/ls/write, no workspace jail)."""
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))

    def _is_credential_path(self, absolute_path: str) -> bool:
        """Block ~/.cow (like ls.py) and /proc/*/environ (like read.py's
        #2913 fix), checked per-file right before opening — not just
        directories pruned during traversal — so a symlink can't bypass this
        via `open()`. Checks both normalized and realpath forms since
        resolving symlinks can change which one matches the /proc regex.

        Intentionally broader than read.py's ~/.cow/.env-only check — don't
        narrow this to match it.
        """
        candidates = set()
        try:
            candidates.add(os.path.normpath(absolute_path).replace(os.sep, "/"))
            candidates.add(os.path.realpath(absolute_path).replace(os.sep, "/"))
        except OSError:
            candidates.add(absolute_path.replace(os.sep, "/"))

        for candidate in candidates:
            if _PROC_ENVIRON_RE.match(candidate):
                return True

        return any(c == self._cow_dir or c.startswith(self._cow_dir + "/") for c in candidates)

    def _search(self, compiled_pattern: re.Pattern, root: str, file_glob: str, max_results: int) -> Tuple[List[Dict[str, Any]], bool, bool, bool]:
        """Walk the tree under `root`, collecting up to `max_results` matches.

        Returns (matches, timed_out, pattern_timeout, skip_list_pruned).
        Traversal order is sorted so that truncated results (common once
        max_results is hit) are deterministic across runs — os.walk's raw
        order otherwise depends on the filesystem.
        """
        matches: List[Dict[str, Any]] = []
        deadline = time.monotonic() + self.timeout
        pattern_timeout = False
        skip_list_pruned = False

        for dirpath, dirnames, filenames in os.walk(root):
            kept_dirnames = []
            for d in dirnames:
                if d in _SKIP_DIR_NAMES:
                    skip_list_pruned = True
                    continue
                if self._is_credential_path(os.path.join(dirpath, d)):
                    continue
                kept_dirnames.append(d)
            dirnames[:] = sorted(kept_dirnames)

            for filename in sorted(filenames):
                if len(matches) >= max_results:
                    return matches, False, pattern_timeout, skip_list_pruned
                if time.monotonic() >= deadline:
                    return matches, True, pattern_timeout, skip_list_pruned
                if file_glob and file_glob != "*" and not fnmatch.fnmatch(filename, file_glob):
                    continue

                file_path = os.path.join(dirpath, filename)
                if self._is_credential_path(file_path):
                    continue
                found, hit_timed_out, hit_pattern_timeout = self._search_single_file(
                    file_path, compiled_pattern, root, max_results - len(matches), deadline
                )
                matches.extend(found)
                pattern_timeout = pattern_timeout or hit_pattern_timeout
                if hit_timed_out:
                    return matches, True, pattern_timeout, skip_list_pruned

        return matches, False, pattern_timeout, skip_list_pruned

    @staticmethod
    def _search_single_file(file_path: str, compiled_pattern: re.Pattern, root: str, remaining: int, deadline: float) -> Tuple[List[Dict[str, Any]], bool, bool]:
        """Search one file, returning (matches, timed_out, pattern_timeout) with
        at most `remaining` matches. Skips oversized/binary/unreadable files.

        `deadline` bounds the whole file, not just each line — without it, a
        file with many individually-cheap lines could still blow past
        self.timeout in aggregate, since no single regex.search() call would
        ever hit REGEX_MATCH_TIMEOUT_SECONDS to trigger the other check.
        """
        try:
            if os.path.getsize(file_path) > MAX_FILE_BYTES:
                return [], False, False
        except OSError:
            return [], False, False

        try:
            # utf-8-sig (matches read.py) strips a leading BOM; plain utf-8
            # would leave it as a stray char and break patterns anchored to line 1.
            with open(file_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            return [], False, False

        found: List[Dict[str, Any]] = []
        for line_no, raw_line in enumerate(content.split("\n"), start=1):
            # Strip a CRLF-artifact trailing \r (content.split("\n") alone
            # leaves it) so $-anchors and returned match text behave the same
            # on Windows-authored files as on \n-only ones.
            line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
            if len(found) >= remaining:
                break
            if time.monotonic() >= deadline:
                return found, True, False
            try:
                matched = compiled_pattern.search(line, timeout=REGEX_MATCH_TIMEOUT_SECONDS)
            except TimeoutError:
                return found, False, True
            if matched:
                truncated_content, _ = truncate_line(line)
                found.append({
                    "file": os.path.relpath(file_path, root),
                    "line": line_no,
                    "match": truncated_content,
                })
        return found, False, False
