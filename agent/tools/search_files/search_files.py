"""
search_files tool - search inside workspace files, or find files by name.

Two questions, one tool: target='content' greps file contents, target='files'
matches file names. They are packaged together because "find the thing" is one
intent from the model's point of view, and because a tool named `grep` never
cued the model to try it for a filename lookup - it would burn turns grepping
for the name, then fall back to shelling out to `find`.

The name-matching path is plain Python (see _find_by_name). Everything below
concerns content search.

Backend strategy (4-tier, first available wins):
    1. ripgrep (rg)               - fastest; respects .gitignore natively
    2. grep -E                    - POSIX systems always have it
    3. PowerShell Select-String   - Windows without rg/grep (.NET regex)
    4. pure Python (os.walk + re) - last-resort fallback, always works

The external backends (1-3) keep search fast on every platform that ships a
real search tool; the pure-Python tier guarantees the tool still returns
results on a bare Windows box where none of them exist (that was the original
motivation for this tool). Only tier 1 honors .gitignore; all tiers additionally
skip a fixed VCS/dependency directory denylist so results stay comparable across
backends. no_ignore=true lifts both. A search that finds nothing while such a
directory is present says so, naming it - which is the only time the exclusion
is worth a word.
"""

import fnmatch
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Any, List, Tuple

import regex as re  # not stdlib re: .search() takes a real per-call timeout, stdlib re has none

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.truncate import truncate_line
from common.log import logger
from common.utils import expand_path

# Short label per backend method, surfaced in a debug log so we can tell which
# search engine actually ran when triaging platform-specific issues.
_BACKEND_LABELS = {
    "_backend_rg": "rg",
    "_backend_grep": "grep",
    "_backend_powershell": "powershell",
    "_backend_python": "python",
}

DEFAULT_MAX_RESULTS = 50
MAX_RESULTS_CAP = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
SEARCH_TIMEOUT_SECONDS = 30
MAX_GLOB_ALTERNATIVES = 256
REGEX_MATCH_TIMEOUT_SECONDS = 1  # caps one regex.search() call in the python backend

_IS_WIN = sys.platform == "win32"

# Matches read.py's issue #2913 fix: /proc/<pid|self|thread-self>/environ
# mirrors any secrets loaded into the process environment from ~/.cow/.env.
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

# VCS + dependency/build dirs excluded by the non-rg backends (rg uses
# .gitignore instead). Kept in sync with what rg would typically skip via a
# project's .gitignore, so cross-backend results stay comparable.
_SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
    "target", "vendor", ".tox", "coverage", ".idea",
}

def _ps_quote(value: str) -> str:
    """Escape a value for a PowerShell single-quoted string literal (quotes
    included).

    A PowerShell single-quoted string ends at the FIRST unescaped quote, and
    the only escape it has is a doubled one. A path or glob holding an
    apostrophe (`O'Brien`, `John's Project`) therefore used to close the
    literal early and made PowerShell reject the whole script with
    "The string is missing the terminator: '." - the model then got a
    successful search reporting zero matches for text that was there.
    """
    return "'" + value.replace("'", "''") + "'"


def _brace_group(pattern: str):
    """Find a comma-separated brace group outside escaped text/character classes."""
    groups = []
    escaped = False
    class_start = None
    for index, char in enumerate(pattern):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if class_start is not None:
            # A class may start with a literal ']', after optional negation.
            first_member = class_start + 1
            if pattern[first_member:first_member + 1] in ("!", "^"):
                first_member += 1
            if char == "]" and index > first_member:
                class_start = None
            continue
        if char == "[":
            class_start = index
        else:
            if char == "{":
                groups.append((index, []))
            elif char == "," and groups:
                groups[-1][1].append(index)
            elif char == "}" and groups:
                start, commas = groups.pop()
                if commas:
                    boundaries = [start] + commas + [index]
                    alternatives = [pattern[a + 1:b] for a, b in zip(boundaries, boundaries[1:])]
                    return start, index, alternatives
    return None


def _expand_glob_braces(pattern: str) -> List[str]:
    """Expand existing ``*.{ts,tsx}`` alternatives without invoking a shell."""
    pending = [pattern]
    expanded = []
    while pending:
        current = pending.pop()
        group = _brace_group(current)
        if group is None:
            expanded.append(current)
            continue
        start, end, alternatives = group
        if len(expanded) + len(pending) + len(alternatives) > MAX_GLOB_ALTERNATIVES:
            raise ValueError(f"file_glob exceeds {MAX_GLOB_ALTERNATIVES} expanded alternatives; use a narrower filter")
        pending.extend(current[:start] + choice + current[end + 1:] for choice in reversed(alternatives))
    return list(dict.fromkeys(expanded))


def _python_file_glob(pattern: str) -> str:
    """Translate escaped glob literals to fnmatch's literal-character syntax."""
    translated = []
    escaped = False
    for char in pattern:
        if escaped:
            translated.append({"[": "[[]", "]": "[]]", "*": "[*]", "?": "[?]"}.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            translated.append(char)
    if escaped:
        translated.append("\\")
    return "".join(translated)


def _pruned_dirs(root: str, max_depth: int = 2) -> List[str]:
    """Denylisted directory names actually present under ``root``.

    The external backends prune inside their own subprocess and cannot report
    back, so we look for ourselves. Only called on an empty result, and only a
    couple of levels deep - which is where these directories sit in practice.
    """
    start = root if os.path.isdir(root) else os.path.dirname(root)
    found = set()

    def scan(path: str, depth: int) -> None:
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if entry.name in _SKIP_DIR_NAMES:
                found.add(entry.name)
            elif depth < max_depth:
                scan(entry.path, depth + 1)

    scan(start, 1)
    return sorted(found)


class SearchFiles(BaseTool):
    """Tool for searching file contents by pattern across a directory tree."""

    name: str = "search_files"
    description: str = (
        "Search file contents, or find files by name. Prefer this over running "
        "grep/rg/find in the bash tool.\n"
        "Content search (target='content', default): regex search inside files, returning "
        "matching lines with their file path and line number. Narrow with file_glob, "
        "choose the result shape with output_mode.\n"
        "File search (target='files'): find files by a name glob such as '*.py' or "
        "'*report*', recursively under path, ordered most-recently-modified first."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex to search for inside files, or - when target='files' - a glob matched against the file name, e.g. '*.py' or '*report*'."
            },
            "target": {
                "type": "string",
                "enum": ["content", "files"],
                "description": "'content' searches inside files (default); 'files' finds files by name."
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in (default: workspace root). Relative paths are based on the workspace directory."
            },
            "file_glob": {
                "type": "string",
                "description": "Glob to filter which files are searched, e.g. '*.py' or '*.{ts,tsx}' (default: all files)."
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files", "count"],
                "description": "content = matching lines with line numbers (default); files = only file paths that contain a match; count = number of matches per file."
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive match (default false)."
            },
            "no_ignore": {
                "type": "boolean",
                "description": "When true, search everywhere: files ignored via .gitignore, plus dependency/build directories (node_modules, dist, vendor, .venv, ...) that are skipped by default. Default false."
            },
            "max_results": {
                "type": "integer",
                "description": f"Maximum number of results to return (default: {DEFAULT_MAX_RESULTS}, capped at {MAX_RESULTS_CAP})."
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

    # --------------------------------------------------------- file-name search
    def _find_by_name(self, pattern: str, root: str, ignore_case: bool,
                      no_ignore: bool, max_results: int) -> ToolResult:
        """Find files whose name matches a glob.

        Answers "where is that file?", which content search cannot: grepping for
        a filename only finds files that mention it, not the file itself.

        Pure Python rather than shelling out to find/rg: the tree walk is the
        cheap part, and it keeps the denylist and result ordering identical on
        every platform.

        Results are ordered most-recently-modified first - when several files
        match, the one just worked on is almost always the one wanted.
        """
        # fnmatch.fnmatch normalizes case only on Windows. Honor the explicit
        # option on every platform while keeping the default case-sensitive.
        if ignore_case:
            pattern = pattern.casefold()
        # A bare "report" is far more likely to mean "name contains report"
        # than an exact filename; a pattern with no wildcard would otherwise
        # match nothing and look like the file does not exist.
        if not any(ch in pattern for ch in "*?["):
            pattern = f"*{pattern}*"

        deadline = time.monotonic() + self.timeout
        hits = []
        timed_out = False

        if os.path.isfile(root):
            walk_root, only = os.path.dirname(root), os.path.basename(root)
        else:
            walk_root, only = root, None

        for dirpath, dirnames, filenames in os.walk(walk_root):
            if time.monotonic() > deadline:
                timed_out = True
                break
            kept = []
            for d in dirnames:
                if d in _SKIP_DIR_NAMES and not no_ignore:
                    continue
                if self._is_credential_path(os.path.join(dirpath, d)):
                    continue
                kept.append(d)
            # An explicit file path scopes this search to that one file, not
            # nested files that happen to have the same basename.
            dirnames[:] = [] if only else sorted(kept)

            for filename in filenames:
                if only and filename != only:
                    continue
                candidate = filename.casefold() if ignore_case else filename
                if not fnmatch.fnmatchcase(candidate, pattern):
                    continue
                full = os.path.join(dirpath, filename)
                if self._is_credential_path(full):
                    continue
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                hits.append((mtime, self._rel(full, root)))

        hits.sort(key=lambda h: (-h[0], h[1]))
        files = [rel for _, rel in hits[:max_results]]

        payload = {"files": files, "match_count": len(files)}
        notices = []
        if len(hits) > max_results:
            notices.append(
                f"{len(hits)} files matched, showing the {max_results} most recently "
                f"modified. Narrow `pattern` or `path`, or raise max_results."
            )
        if timed_out:
            notices.append(
                f"Search stopped after {self.timeout}s - results may be incomplete. "
                f"Narrow `path`."
            )
        if not files and not no_ignore:
            pruned = _pruned_dirs(root)
            if pruned:
                notices.append(
                    f"Skipped {', '.join(pruned)}. Use no_ignore=true to search them too."
                )
        if notices:
            payload["notice"] = " ".join(notices)
        return ToolResult.success(payload)

    # ------------------------------------------------------------------ execute
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """Execute a content search. See params for arguments.

        Returns a ToolResult whose payload shape depends on output_mode:
          content -> {matches: [{file, line, match}], match_count, notice?}
          files   -> {files: [path, ...], match_count, notice?}
          count   -> {counts: [{file, count}], match_count, notice?}
        """
        pattern = args.get("pattern", "")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.fail("Error: pattern parameter is required")

        target = args.get("target", "content") or "content"
        if target not in ("content", "files"):
            return ToolResult.fail(f"Error: target must be content/files, got: {target!r}")

        path = args.get("path", ".") or "."
        file_glob = args.get("file_glob", "*") or "*"
        if not isinstance(file_glob, str):
            return ToolResult.fail(f"Error: file_glob must be a string, got: {file_glob!r}")

        try:
            _expand_glob_braces(file_glob)
        except ValueError as exc:
            return ToolResult.fail(f"Error: {exc}")

        output_mode = args.get("output_mode", "content") or "content"
        if output_mode not in ("content", "files", "count"):
            return ToolResult.fail(f"Error: output_mode must be content/files/count, got: {output_mode!r}")

        ignore_case = bool(args.get("ignore_case", False))
        no_ignore = bool(args.get("no_ignore", False))

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

        # Validate regex early so a bad pattern fails the same way on every
        # backend (external tools would otherwise emit their own error text).
        # In file mode the pattern is a glob, not a regex.
        if target == "content":
            try:
                re.compile(pattern)
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

        if target == "files":
            return self._find_by_name(pattern, root, ignore_case, no_ignore, max_results)

        opts = _SearchOptions(
            pattern=pattern, root=root, file_glob=file_glob,
            output_mode=output_mode, ignore_case=ignore_case,
            no_ignore=no_ignore, max_results=max_results, deadline=time.monotonic() + self.timeout,
        )

        backend = self._pick_backend()
        used = _BACKEND_LABELS.get(backend.__name__, backend.__name__)
        try:
            outcome = backend(opts)
        except Exception as e:
            # Any backend failure falls through to python so the tool never
            # hard-fails just because an external binary misbehaved.
            if backend is not self._backend_python:
                logger.warning(f"[SearchFiles] backend '{used}' failed ({e}); falling back to python")
                used = "python(fallback)"
                outcome = self._backend_python(opts)
            else:
                return ToolResult.fail(f"Error searching files: {e}")

        logger.debug(f"[SearchFiles] backend={used} mode={opts.output_mode} matches={len(outcome.rows)}")
        return self._format(outcome, opts)

    # ------------------------------------------------------------- backend pick
    def _pick_backend(self):
        """Return the best available backend callable for this machine."""
        if shutil.which("rg"):
            return self._backend_rg
        if not _IS_WIN and shutil.which("grep"):
            return self._backend_grep
        if _IS_WIN and (shutil.which("powershell") or shutil.which("pwsh")):
            return self._backend_powershell
        return self._backend_python

    # ------------------------------------------------------------------ helpers
    def _resolve_path(self, path: str) -> str:
        """Resolve to absolute path (same convention as read/ls/write, no workspace jail)."""
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))

    def _is_credential_path(self, absolute_path: str) -> bool:
        """Block ~/.cow (like ls.py) and /proc/*/environ (like read.py #2913)."""
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

    def _rel(self, file_path: str, root: str) -> str:
        # Always emit forward slashes so paths are consistent across platforms
        # (Windows os.path.relpath yields 'sub\\b.py') and safe to feed back
        # into read/edit, which accept '/'.
        try:
            base = root if os.path.isdir(root) else os.path.dirname(root)
            rel = os.path.relpath(file_path, base)
        except ValueError:
            rel = file_path
        return rel.replace(os.sep, "/")

    # ------------------------------------------------------------- rg backend
    def _backend_rg(self, opts: "_SearchOptions") -> "_BackendResult":
        cmd = ["rg", "--null", "--line-number", "--no-heading", "--with-filename", "--color", "never"]
        # Exclude the same VCS/dependency dirs the other backends hardcode, so a
        # repo WITHOUT a .gitignore still gives identical results across backends
        # (rg alone would otherwise only skip what .gitignore lists).
        if not opts.no_ignore:
            for d in _SKIP_DIR_NAMES:
                cmd += ["--glob", f"!{d}"]
        # Keep a bounded source preview instead of rg's omission placeholder;
        # truncate_line applies the same display limit as the other backends.
        cmd += ["--max-columns", "1000", "--max-columns-preview"]
        if opts.ignore_case:
            cmd.append("-i")
        if opts.no_ignore:
            cmd.append("--no-ignore")
        if opts.file_glob and opts.file_glob != "*":
            cmd += ["--glob", opts.file_glob]
        if opts.output_mode == "files":
            cmd.append("-l")
        elif opts.output_mode == "count":
            cmd.append("-c")
        # `--` guards patterns that begin with a dash.
        cmd += ["-e", opts.pattern, "--", opts.root]
        rows, timed_out = self._run_external(cmd, opts)
        return _BackendResult(rows, timed_out)

    # ------------------------------------------------------------ grep backend
    def _backend_grep(self, opts: "_SearchOptions") -> "_BackendResult":
        # -H forces filename even for a single-file target; -r recurses; -E = ERE
        # (aligns alternation/quantifier syntax with rg). -n is added only in
        # content mode — mixing it with -c/-l corrupts their output.
        cmd = ["grep", "--null", "-rH", "-E"]
        if not opts.no_ignore:
            for d in _SKIP_DIR_NAMES:
                cmd.append(f"--exclude-dir={d}")
        if opts.ignore_case:
            cmd.append("-i")
        if opts.file_glob and opts.file_glob != "*":
            for pattern in _expand_glob_braces(opts.file_glob):
                cmd.append(f"--include={pattern}")
        if opts.output_mode == "files":
            cmd.append("-l")
        else:
            cmd.append("-n")
        cmd += ["-e", opts.pattern, opts.root]
        # BSD grep ignores --null with -c; aggregate framed matching lines instead.
        rows, timed_out = self._run_external(cmd, opts, count_from_content=opts.output_mode == "count")
        return _BackendResult(rows, timed_out)

    # ------------------------------------------------ powershell backend (win)
    def _backend_powershell(self, opts: "_SearchOptions") -> "_BackendResult":
        if len(_expand_glob_braces(opts.file_glob)) > 1:
            # PowerShell -Filter accepts one wildcard, not brace alternatives.
            # The existing Python backend implements this documented filter.
            return self._backend_python(opts)
        shell = shutil.which("powershell") or shutil.which("pwsh")
        # Select-String has no per-mode output flags like grep's -l/-c, so it
        # always emits `path:line:content`; files/count are aggregated from that
        # in _parse_powershell (NOT the shared _parse_null_output, whose files/count
        # parsers assume grep-native shapes). Emit an explicit \t between path
        # and line:content so a Windows drive-letter colon (C:\...) never gets
        # mistaken for the field separator.
        ci = "-CaseSensitive" if not opts.ignore_case else ""
        glob_filter = ""
        if opts.file_glob and opts.file_glob != "*":
            glob_filter = f"-Filter {_ps_quote(opts.file_glob)} "
        prune = "" if opts.no_ignore else (
            f"| Where-Object {{ $_.FullName -notmatch '\\\\({'|'.join(_SKIP_DIR_NAMES)})\\\\' }} "
        )
        script = (
            # Force UTF-8 on stdout so non-ASCII file names/content survive the
            # trip to our subprocess reader (Windows PowerShell defaults to the
            # system code page, e.g. cp936, which we'd misread as UTF-8 -> mojibake).
            f"[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            f"$ErrorActionPreference='SilentlyContinue';"
            f"Get-ChildItem -LiteralPath {_ps_quote(opts.root)} -Recurse -File {glob_filter}"
            f"{prune}"
            f"| Select-String -Pattern @'\n{opts.pattern}\n'@ {ci} "
            f"| ForEach-Object {{ \"$($_.Path)`t$($_.LineNumber):$($_.Line)\" }}"
        )
        cmd = [shell, "-NoProfile", "-NonInteractive", "-Command", script]
        remaining = max(0.1, opts.deadline - time.monotonic())
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            return _BackendResult([], True)
        rows = self._parse_powershell((proc.stdout or "").splitlines(), opts)
        # A script PowerShell could not parse - or a root it could not
        # enumerate - exits non-zero with empty stdout, which is byte-for-byte
        # what "searched everything and found nothing" looks like. Reading the
        # exit code is what keeps a failed search from being reported to the
        # model as a successful empty one; execute() turns this into a python
        # retry. Only when there is nothing to keep: a partly-failed run
        # (dangling junction, unreadable subdir) leaves the exit code at 0
        # and its rows are worth having.
        if not rows and proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            raise RuntimeError(
                f"powershell exited {proc.returncode}: {detail[0] if detail else 'no output'}"
            )
        return _BackendResult(rows, False)

    def _parse_powershell(self, lines: List[str], opts: "_SearchOptions") -> List[dict]:
        """Parse Select-String's `path\\tline:content` and aggregate into the
        shape output_mode asks for. The tab guards against ':' inside a Windows
        path (drive letter); line:content is split on the first ':' after it."""
        content_rows: List[dict] = []
        counts: Dict[str, int] = {}
        for line in lines:
            if not line or "\t" not in line:
                continue
            path_part, rest = line.split("\t", 1)
            head, sep, body = rest.partition(":")
            if not sep or not head.isdigit():
                continue
            rel = self._rel(path_part, opts.root)
            counts[rel] = counts.get(rel, 0) + 1
            truncated, _ = truncate_line(body)
            content_rows.append({"file": rel, "line": int(head), "match": truncated})

        if opts.output_mode == "files":
            seen = []
            for r in content_rows:
                if r["file"] not in seen:
                    seen.append(r["file"])
            rows = [{"file": f} for f in sorted(seen)]
        elif opts.output_mode == "count":
            rows = [{"file": f, "count": c} for f, c in sorted(counts.items())]
        else:
            content_rows.sort(key=lambda r: (r["file"], r["line"]))
            rows = content_rows
        return rows[:opts.max_results]

    # ----------------------------------------------- external runner + parser
    def _run_external(
        self, cmd: List[str], opts: "_SearchOptions", count_from_content: bool = False,
    ) -> Tuple[List[dict], bool]:
        remaining = max(0.1, opts.deadline - time.monotonic())
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=remaining)
        except subprocess.TimeoutExpired:
            return [], True
        # Binary capture avoids universal-newline conversion inside filenames.
        output = (proc.stdout or b"").decode("utf-8", errors="replace")
        rows = self._parse_null_output(output, opts, count_from_content)
        # Exit 1 is "no matches". Exit 2 with rows is a partial result (an
        # unreadable file); without rows it is a real failure, e.g. ripgrep
        # rejecting lookaround, and execute() falls back to Python.
        if not rows and proc.returncode not in (0, 1):
            diagnostic = (proc.stderr or b"").decode("utf-8", errors="replace").strip()[:1000]
            raise RuntimeError(f"search process exited {proc.returncode}: {diagnostic}")
        return rows, False

    def _parse_null_output(
        self, output: str, opts: "_SearchOptions", count_from_content: bool = False,
    ) -> List[dict]:
        """Both external tools delimit filenames with NUL, never ':' or LF."""
        rows: List[dict] = []
        counts: Dict[str, int] = {}
        offset = 0
        while offset < len(output):
            separator = output.find("\0", offset)
            if separator < 0:
                break
            path = output[offset:separator]
            offset = separator + 1
            if opts.output_mode == "files":
                rows.append({"file": self._rel(path, opts.root)})
                continue
            end = output.find("\n", offset)
            if end < 0:
                end = len(output)
            body = output[offset:end]
            if body.endswith("\r"):
                body = body[:-1]
            offset = end + 1
            if opts.output_mode == "count" and not count_from_content:
                if body.isdigit() and int(body) > 0:
                    rows.append({"file": self._rel(path, opts.root), "count": int(body)})
                continue
            line_no, separator, content = body.partition(":")
            if not separator or not line_no.isdigit():
                continue
            if count_from_content:
                file = self._rel(path, opts.root)
                counts[file] = counts.get(file, 0) + 1
            else:
                truncated, _ = truncate_line(content)
                rows.append({"file": self._rel(path, opts.root), "line": int(line_no), "match": truncated})
        if count_from_content:
            rows = [{"file": file, "count": count} for file, count in counts.items()]
        # Deterministic order across backends.
        if opts.output_mode == "content":
            rows.sort(key=lambda row: (row["file"], row["line"]))
        else:
            rows.sort(key=lambda row: row["file"])
        return rows[:opts.max_results]

    # ------------------------------------------------------- python fallback
    def _backend_python(self, opts: "_SearchOptions") -> "_BackendResult":
        flags = re.IGNORECASE if opts.ignore_case else 0
        compiled = re.compile(opts.pattern, flags)
        rows: List[dict] = []
        pattern_timeout = False
        root = opts.root
        file_globs = [_python_file_glob(pattern) for pattern in _expand_glob_braces(opts.file_glob)]

        walk_root = root if os.path.isdir(root) else os.path.dirname(root)
        single_file = None if os.path.isdir(root) else os.path.basename(root)

        for dirpath, dirnames, filenames in os.walk(walk_root):
            kept = []
            for d in dirnames:
                if d in _SKIP_DIR_NAMES and not opts.no_ignore:
                    continue
                if self._is_credential_path(os.path.join(dirpath, d)):
                    continue
                kept.append(d)
            # A file target is scoped to that file, not nested namesakes.
            dirnames[:] = [] if single_file else sorted(kept)

            for filename in sorted(filenames):
                if single_file and filename != single_file:
                    continue
                if len(rows) >= opts.max_results:
                    return _BackendResult(self._python_finalize(rows, opts), False, pattern_timeout)
                if time.monotonic() >= opts.deadline:
                    return _BackendResult(self._python_finalize(rows, opts), True, pattern_timeout)
                if opts.file_glob and opts.file_glob != "*" and not any(fnmatch.fnmatch(filename, pattern) for pattern in file_globs):
                    continue
                fp = os.path.join(dirpath, filename)
                if self._is_credential_path(fp):
                    continue
                file_rows, hit_deadline, hit_pattern_timeout = self._python_scan_file(fp, compiled, opts)
                rows.extend(file_rows)
                pattern_timeout = pattern_timeout or hit_pattern_timeout
                if hit_deadline:
                    return _BackendResult(self._python_finalize(rows, opts), True, pattern_timeout)

        return _BackendResult(self._python_finalize(rows, opts), False, pattern_timeout)

    def _python_scan_file(self, fp: str, compiled, opts: "_SearchOptions") -> Tuple[List[dict], bool, bool]:
        try:
            if os.path.getsize(fp) > MAX_FILE_BYTES:
                return [], False, False
        except OSError:
            return [], False, False
        try:
            with open(fp, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            return [], False, False

        out: List[dict] = []
        count = 0
        for line_no, raw in enumerate(content.split("\n"), start=1):
            line = raw[:-1] if raw.endswith("\r") else raw
            if time.monotonic() >= opts.deadline:
                return out, True, False
            try:
                matched = compiled.search(line, timeout=REGEX_MATCH_TIMEOUT_SECONDS)
            except TimeoutError:
                # Bail on this file's remaining lines but flag it so the caller
                # can warn the model results may be incomplete.
                return out, False, True
            if matched:
                count += 1
                if opts.output_mode == "content":
                    truncated, _ = truncate_line(line)
                    out.append({"file": self._rel(fp, opts.root), "line": line_no, "match": truncated})
                elif opts.output_mode == "files":
                    out.append({"file": self._rel(fp, opts.root)})
                    break
        if opts.output_mode == "count" and count:
            out.append({"file": self._rel(fp, opts.root), "count": count})
        return out, False, False

    @staticmethod
    def _python_finalize(rows: List[dict], opts: "_SearchOptions") -> List[dict]:
        if opts.output_mode == "content":
            rows.sort(key=lambda r: (r["file"], r["line"]))
        else:
            rows.sort(key=lambda r: r["file"])
        return rows[:opts.max_results]

    # ------------------------------------------------------------- formatting
    def _format(self, outcome: "_BackendResult", opts: "_SearchOptions") -> ToolResult:
        rows = outcome.rows
        notices: List[str] = []
        if opts.output_mode == "files":
            payload = {"files": [r["file"] for r in rows], "match_count": len(rows)}
        elif opts.output_mode == "count":
            payload = {"counts": rows, "match_count": sum(r.get("count", 0) for r in rows)}
        else:
            payload = {"matches": rows, "match_count": len(rows)}

        if len(rows) >= opts.max_results:
            if opts.max_results >= MAX_RESULTS_CAP:
                notices.append(f"{opts.max_results} result limit reached (hard maximum). Narrow `path` or `file_glob`.")
            else:
                notices.append(
                    f"{opts.max_results} result limit reached. "
                    f"Use max_results={min(opts.max_results * 2, MAX_RESULTS_CAP)} to see more."
                )
        if outcome.timed_out:
            notices.append(
                f"Search stopped after {self.timeout}s — results may be incomplete. "
                f"Narrow `path` or `file_glob`."
            )
        if outcome.pattern_timeout:
            notices.append(
                f"Pattern took longer than {REGEX_MATCH_TIMEOUT_SECONDS}s on a line in one or more "
                f"files — the rest of that file was not searched. Results may be incomplete. "
                f"Simplify `pattern` to avoid catastrophic backtracking."
            )
        # Only worth saying when the search came up empty AND a denylisted
        # directory is really there: otherwise it is noise on every call, and
        # in a tree without one it is simply untrue.
        if not rows and not opts.no_ignore:
            pruned = _pruned_dirs(opts.root)
            if pruned:
                notices.append(
                    f"Skipped {', '.join(pruned)}. Use no_ignore=true to search them too."
                )
        if notices:
            payload["notice"] = " ".join(notices)
        return ToolResult.success(payload)


class _BackendResult:
    """What a backend returns: rows plus the signals _format turns into notices."""
    __slots__ = ("rows", "timed_out", "pattern_timeout")

    def __init__(self, rows, timed_out=False, pattern_timeout=False):
        self.rows = rows
        self.timed_out = timed_out
        self.pattern_timeout = pattern_timeout


class _SearchOptions:
    """Plain container for a single search invocation's resolved options."""
    __slots__ = ("pattern", "root", "file_glob", "output_mode",
                 "ignore_case", "no_ignore", "max_results", "deadline")

    def __init__(self, pattern, root, file_glob, output_mode,
                 ignore_case, no_ignore, max_results, deadline):
        self.pattern = pattern
        self.root = root
        self.file_glob = file_glob
        self.output_mode = output_mode
        self.ignore_case = ignore_case
        self.no_ignore = no_ignore
        self.max_results = max_results
        self.deadline = deadline
