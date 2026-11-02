"""Permission modes: how much a session is allowed to change.

Three modes, ordered from most to least restrictive:

- ``read-only``       Look, don't touch. File writes are refused, shell commands
                      are limited to an allowlist of read-only utilities, and
                      tool actions with side effects (browser clicks, scheduler
                      writes, env edits) are refused.
- ``workspace-write`` Free rein inside the session's working directory (the
                      project, plus the Agent's own state dir and the system
                      temp dir); writes that land outside it are refused, as
                      are writes to the files that widen the Agent's reach
                      (MCP servers, config, credentials, session settings).
                      Reading anywhere is still allowed.
- ``full-access``     No confinement. The historical behavior, kept as the
                      default so existing installs are untouched.

The mode is resolved per session (see ``agent.workspace.session_prefs``) and
falls back to the global ``agent_permission_mode`` setting.

Scope, and honesty about it: these checks are argument-level, not an OS sandbox.
``write``/``edit`` are exact - the target path is a parameter we resolve. ``bash``
is best effort: we parse the command line and refuse the recognizable
out-of-scope cases (redirects, ``rm``/``mv`` outside the roots, privilege
escalation), but a program the shell starts can still write wherever the OS lets
it. The UI says as much; anyone who needs a hard boundary wants a container.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

READ_ONLY = "read-only"
WORKSPACE_WRITE = "workspace-write"
FULL_ACCESS = "full-access"

MODES: Tuple[str, ...] = (READ_ONLY, WORKSPACE_WRITE, FULL_ACCESS)

# Preserve the behavior installs already have: unless someone opts in, nothing
# is gated. Fresh installs ship a stricter value via config-template.json.
DEFAULT_MODE = FULL_ACCESS

CONFIG_KEY = "agent_permission_mode"

_ALIASES = {
    "readonly": READ_ONLY,
    "read_only": READ_ONLY,
    "ro": READ_ONLY,
    "workspace": WORKSPACE_WRITE,
    "workspace_write": WORKSPACE_WRITE,
    "workspacewrite": WORKSPACE_WRITE,
    "write": WORKSPACE_WRITE,
    "full": FULL_ACCESS,
    "full_access": FULL_ACCESS,
    "fullaccess": FULL_ACCESS,
    "danger-full-access": FULL_ACCESS,
    "all": FULL_ACCESS,
}

_IS_WIN = sys.platform == "win32"


def normalize_mode(value: Any, default: Optional[str] = None) -> str:
    """Coerce anything the API or config may hold into a known mode id."""
    fallback = default if default in MODES else DEFAULT_MODE
    if not isinstance(value, str):
        return fallback
    v = value.strip().lower()
    if v in MODES:
        return v
    return _ALIASES.get(v, fallback)


def global_mode() -> str:
    """The instance-wide default, used by sessions with no override."""
    try:
        from config import conf

        return normalize_mode(conf().get(CONFIG_KEY))
    except Exception:
        return DEFAULT_MODE


@dataclass
class Decision:
    """Outcome of a permission check."""

    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.allowed


ALLOW = Decision(True)


# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

# Tools whose only job is to change a file at a path we can read from the args.
_FILE_WRITE_TOOLS = frozenset({"write", "edit"})

# Tools that change state the user can see outside this conversation.
_MUTATING_TOOLS = frozenset({"evolution_undo"})

# Tools where only some sub-actions mutate: (argument name, mutating values).
_ACTION_TOOLS: Dict[str, Tuple[str, frozenset]] = {
    # Clicking, typing, pressing keys and running scripts act on the page;
    # navigating and reading it does not.
    "browser": ("action", frozenset({"click", "fill", "select", "press", "evaluate"})),
    "scheduler": ("action", frozenset({"create", "delete", "enable", "disable"})),
    "env_config": ("action", frozenset({"set", "delete"})),
}

# Built-in tools that only read. Listed so the MCP name heuristic below never
# fires on a first-party tool, and so unknown names are the only ones guessed at.
_KNOWN_TOOLS = frozenset({
    "read", "ls", "search_files", "memory_search", "memory_get", "web_search",
    "web_fetch", "vision", "send", "subagent", "bash", "write", "edit",
    "browser", "scheduler", "env_config", "evolution_undo", "time",
})

# MCP tools arrive with names we have never seen. Rather than guess "safe", read
# the verb: `create_issue` clearly writes, `list_repos` clearly does not.
# Read-only mode only.
_MUTATING_NAME_RE = re.compile(
    r"(?:^|[_\-.])(create|new|add|insert|write|update|edit|modify|patch|set|put|post|"
    r"delete|remove|drop|destroy|purge|clear|reset|rename|move|upload|publish|deploy|"
    r"send|submit|execute|exec|run|invoke|install|approve|merge|revoke|grant)"
    r"(?:$|[_\-.]|\d)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Shell command classification
# ---------------------------------------------------------------------------

# Commands that only read. Anything absent is refused in read-only mode, so an
# unknown command fails closed.
_READ_ONLY_COMMANDS = frozenset({
    # listing / reading
    "ls", "ll", "cat", "bat", "head", "tail", "nl", "wc", "less", "more", "tree",
    "file", "stat", "du", "df", "basename", "dirname", "realpath", "readlink",
    "pwd", "echo", "printf", "which", "type", "whereis", "locate",
    # searching / comparing
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "find", "fd", "diff", "cmp",
    # text processing (writes are caught per-command by _READ_ONLY_WRITE_FORMS)
    "sort", "uniq", "cut", "paste", "join", "comm", "column", "tr", "awk", "sed",
    "jq", "yq", "xxd", "od", "strings", "fold", "rev", "expand", "unexpand",
    # hashing
    "md5", "md5sum", "sha1sum", "sha256sum", "shasum", "cksum",
    # environment / system inspection
    "date", "cal", "whoami", "id", "groups", "hostname", "uname", "printenv",
    "locale", "uptime", "ps", "free", "vm_stat", "sysctl", "lsof", "netstat",
    "ifconfig", "ip", "dig", "nslookup", "host", "sw_vers", "arch",
    "true", "false", "test", "seq", "sleep", "tty",
    # version control (sub-command checked separately)
    "git",
    # windows shell
    "dir", "findstr", "where", "ver", "systeminfo", "tasklist", "chdir", "cd",
})

# Allowlisted read-only commands that write a file through a flag rather than
# a shell redirect (which is refused separately).
_READ_ONLY_WRITE_FORMS = {
    "find": ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls",
             "-fprint", "-fprintf"),
    "fd": ("--exec", "--exec-batch"),
    "sort": ("--output",),
    "xxd": ("-r", "-revert"),
    "sed": ("--in-place",),
}

# Short write options, which may be clustered (`-uo`) or carry a value (`-i.bak`).
_READ_ONLY_WRITE_SHORT = {"fd": "xX", "sort": "o", "sed": "i"}

_XXD_VALUE_FLAGS = frozenset({"-c", "-cols", "-g", "-groupsize", "-l", "-len",
                              "-n", "-name", "-o", "-offset", "-s", "-seek"})

# `sed` also writes through its `w` command (`sed -e 'w out.txt' in.txt`), which
# takes a bare path inside the script rather than a flag.
_SED_WRITE_COMMAND_RE = re.compile(r"(?:^|[;{}])\s*w\s+\S")

# awk can hand a string to the shell, which makes any statement a write.
_AWK_SHELL_RE = re.compile(r"\bsystem\s*\(|\bgetline\b[^\n]*\||\bprint\b[^\n]*>\s*\"")

# git sub-commands that only read the repository.
_GIT_READ_SUBCOMMANDS = frozenset({
    "status", "log", "diff", "show", "branch", "tag", "remote", "ls-files",
    "ls-tree", "ls-remote", "rev-parse", "rev-list", "describe", "blame",
    "shortlog", "cat-file", "reflog", "grep", "whatchanged", "name-rev",
    "symbolic-ref", "count-objects", "verify-commit", "version", "help",
    "stash", "worktree", "notes", "config", "show-ref", "for-each-ref",
})

# Flags that turn a read-only git sub-command into a write.
_GIT_WRITE_FLAGS = frozenset({
    "-d", "-D", "--delete", "-m", "-M", "--move", "-f", "--force", "--set-upstream",
    "--set-upstream-to", "--unset", "--unset-all", "--add", "--replace-all",
    "--edit", "-e", "--prune", "--rename", "--create", "--amend",
})

# `-c` / `-C` / `--copy` copy a branch under `git branch`, but only select
# rename detection or a config value elsewhere, so they are checked per sub-command.
_GIT_BRANCH_WRITE_FLAGS = frozenset({"-c", "-C", "--copy"})

# git's own options that come before the sub-command and take a value.
_GIT_GLOBAL_VALUE_OPTIONS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
})

# git sub-commands that only read in their "list" form.
_GIT_LIST_ONLY = {"stash": "list", "worktree": "list", "notes": "list"}

# Sub-commands that create a ref when handed a bare name (`git tag v1`), and
# only list when invoked bare or with a listing flag.
_GIT_LIST_OR_CREATE = frozenset({"branch", "tag"})

# Flags that make those sub-commands list. `-a` is branch-only: it annotates a tag.
_GIT_LISTING_FLAGS = frozenset({
    "-l", "--list", "-v", "--verbose", "-i", "--ignore-case",
    "--contains", "--no-contains", "--merged", "--no-merged", "--points-at",
    "--format", "--sort", "--color", "--column", "--no-column",
})

_GIT_EXTRA_LISTING_FLAGS = {
    "branch": frozenset({"-a", "-r", "--all", "--remotes"}),
}

# `git remote` verbs that change remotes; bare `git remote` / `show` only read.
_GIT_REMOTE_WRITE_VERBS = frozenset({
    "add", "rename", "remove", "rm", "set-head", "set-branches", "set-url",
    "prune", "update", "set", "unset",
})

# `git config` only reads with one of these.
_GIT_CONFIG_READ_FLAGS = frozenset({
    "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l",
})

# Commands that create, delete or overwrite files at paths readable off the
# command line. Used by workspace-write to keep changes inside the roots.
# Package managers are deliberately absent: `pip install` writes outside the
# workspace by design, and refusing it would break ordinary work for a boundary
# this mode never promised to enforce.
_PATH_MUTATING_COMMANDS = frozenset({
    "rm", "rmdir", "unlink", "mv", "cp", "rsync", "install", "dd", "truncate",
    "shred", "ln", "mkdir", "touch", "chmod", "chown", "chgrp", "chflags",
    "tee", "sed", "zip", "unzip", "tar", "gzip", "gunzip", "del", "erase",
    "move", "copy", "ren", "rename", "md", "rd",
    # Allowlisted text tools whose write form is a flag rather than a redirect.
    "find", "fd", "sort", "xxd", "awk",
})

# For these only the destination (last positional) is written; reading a source
# from outside the workspace is fine.
_DESTINATION_ONLY_COMMANDS = frozenset({
    "cp", "copy", "rsync", "install", "ln", "unzip", "tar", "zip",
})

# These commands name their destination with a flag instead of with an operand,
# so the last operand is a source and the write itself goes unchecked. The
# value is the short option letter, the long spelling of the same option and
# the short options that carry a value of their own.
_FLAG_DESTINATIONS = {
    "cp": ("t", "--target-directory", "SZ"),
    "copy": ("t", "--target-directory", "SZ"),
    "install": ("t", "--target-directory", "SZmog"),
    "ln": ("t", "--target-directory", "SZ"),
    "move": ("t", "--target-directory", "SZ"),
    "mv": ("t", "--target-directory", "SZ"),
    "unzip": ("d", "", "xP"),
}

# A tar run writes the archive -f names when it creates one and the directory
# -C names when it extracts one; listing and comparing write nothing.
_TAR_MODES = {
    "c": "f", "u": "f", "r": "f", "A": "f", "x": "C", "t": "", "d": "",
    "--create": "f", "--update": "f", "--append": "f", "--concatenate": "f",
    "--delete": "f", "--extract": "C", "--get": "C",
    "--list": "", "--diff": "", "--compare": "",
}

# The tar options that carry a value of their own.
_TAR_VALUES = "fCTbXS"

# When their last operand is a directory, the sources land inside it by name.
_INTO_DIRECTORY_COMMANDS = frozenset({
    "mv", "move", "cp", "copy", "rsync", "install", "ln",
})

# Privilege escalation is out of scope for every gated mode.
_ESCALATION_COMMANDS = frozenset({"sudo", "doas", "su", "runas", "pkexec"})

# Wrappers that run another command; the real command follows.
_WRAPPER_COMMANDS = frozenset({
    "env", "nohup", "time", "timeout", "nice", "ionice", "stdbuf", "xargs",
    "command", "builtin", "exec", "watch", "setsid",
})

# Redirect targets that are not real files.
_NULL_SINKS = frozenset({
    "/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/fd/1", "/dev/fd/2",
    "nul", "NUL", "con", "CON",
})

# Tokens that end one command and start the next. Redirect operators are absent
# on purpose: they belong to the command they follow.
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", "(", ")", "{", "}", "\n"})

_OPERATOR_CHARS = set("<>&|;()")

# shlex does not treat backquotes as quotes, so ``echo `cmd``` lexes as one
# token; the substituted command has to become its own segment.
_BACKTICK_RE = re.compile(r"(?<!\\)`([^`]*)`")

# ``<(cmd)`` / ``>(cmd)``: shlex emits ``<(`` as a plain token.
_PROCESS_SUBST_CHARS = frozenset({"<", ">"})
# Placeholder for a substitution passed as an argument; neither gate reads it.
_SUBSTITUTION = "\x00"


def _is_operator(token: str) -> bool:
    return bool(token) and all(ch in _OPERATOR_CHARS for ch in token)


def _split_process_substitutions(command: str) -> Tuple[str, List[str]]:
    """Pull the bodies of ``<(...)`` / ``>(...)`` out of ``command``.

    Returns the outer line with each substitution collapsed to a placeholder,
    plus the bodies to classify on their own. Quoting is honoured so a ``(``
    inside a string does not open a substitution.
    """
    bodies: List[str] = []
    out: List[str] = []
    quote = ""
    i = 0
    while i < len(command):
        char = command[i]
        if quote:
            out.append(char)
            if char == quote and (i == 0 or command[i - 1] != "\\"):
                quote = ""
            i += 1
            continue
        if char in "'\"":
            quote = char
            out.append(char)
            i += 1
            continue
        if char == "\\" and i + 1 < len(command):
            out.append(command[i : i + 2])
            i += 2
            continue
        if char in _PROCESS_SUBST_CHARS and command[i + 1 : i + 2] == "(":
            depth = 1
            j = i + 2
            body: List[str] = []
            while j < len(command) and depth:
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                    if not depth:
                        j += 1
                        break
                body.append(command[j])
                j += 1
            if depth:
                # Unbalanced: leave the text alone rather than guess.
                out.append(command[i:j])
            else:
                bodies.append("".join(body))
                out.append(_SUBSTITUTION)
            i = j
            continue
        out.append(char)
        i += 1
    return "".join(out), bodies


def _collect_segments(command: str, segments: List[List[str]]) -> bool:
    """Append the token lists of ``command`` and of anything it substitutes.

    Returns False when any part cannot be lexed, so the whole line fails closed.
    """
    command = _BACKTICK_RE.sub(
        lambda match: f"$({match.group(1).strip()})" if match.group(1).strip() else "",
        command,
    )
    outer, bodies = _split_process_substitutions(command)
    # Classify substituted bodies first so the outer command cannot mask them.
    for body in bodies:
        if not _collect_segments(body, segments):
            return False

    lexer = shlex.shlex(outer, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False

    current: List[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return True


def _parse_segments(command: str) -> Optional[List[List[str]]]:
    """Split a command line into per-command token lists, honoring quotes.

    ``punctuation_chars`` makes the lexer emit ``&&``, ``|``, ``>`` and friends
    as their own tokens while leaving quoted text alone, so ``grep "a|b"`` is one
    command and not two. Returns None when the line cannot be lexed at all.
    """
    segments: List[List[str]] = []
    if not _collect_segments(command or "", segments):
        return None
    return segments


def _command_name(tokens: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    """Return ``(command, args)``, unwrapping ``VAR=x``/``env``/``nohup``/... .

    So ``env FOO=1 nohup rm -rf /`` is classified as ``rm``.
    """
    args = list(tokens)
    while args:
        head = args[0]
        if _is_operator(head):
            args = args[1:]
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            args = args[1:]
            continue
        name = os.path.basename(head).lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name in _WRAPPER_COMMANDS:
            args = args[1:]
            while args and args[0].startswith("-"):
                args = args[1:]
            continue
        return name, args[1:]
    return None, []


def _redirect_targets(tokens: Sequence[str]) -> List[str]:
    """Paths this command redirects output into (fd duplications excluded)."""
    targets: List[str] = []
    for i, token in enumerate(tokens):
        if ">" not in token or not _is_operator(token):
            continue
        if i + 1 >= len(tokens):
            continue
        target = tokens[i + 1]
        # `2>&1` / `>&-`: duplicating or closing a descriptor, not a file.
        if "&" in token and (target.isdigit() or target == "-"):
            continue
        if _is_operator(target):
            continue
        targets.append(target)
    return targets


def _positional_paths(args: Sequence[str]) -> List[str]:
    """Non-flag operands, which for file commands are the paths it touches."""
    out: List[str] = []
    skip_next = False
    for i, token in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if _is_operator(token):
            skip_next = True  # its operand belongs to the redirect
            continue
        if token.startswith("-"):
            continue
        nxt = args[i + 1] if i + 1 < len(args) else None
        # A bare fd number in front of a redirect (`2> log`) is not a path.
        if token.isdigit() and nxt and _is_operator(nxt):
            continue
        out.append(token)
    return out


# ---------------------------------------------------------------------------
# Path containment
# ---------------------------------------------------------------------------

def _real(path: str, cwd: Optional[str]) -> str:
    expanded = os.path.expanduser(os.path.expandvars(path))
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd or os.getcwd(), expanded)
    return os.path.realpath(expanded)


def _normalize_roots(roots: Optional[Iterable[str]], cwd: Optional[str]) -> List[str]:
    """Absolute, de-duplicated write roots, always including cwd and temp."""
    out: List[str] = []
    for root in list(roots or []) + [cwd, tempfile.gettempdir()]:
        if not root:
            continue
        try:
            real = os.path.realpath(os.path.expanduser(root))
        except Exception:
            continue
        if real and real not in out:
            out.append(real)
    return out


def _inside_roots(path: str, roots: Sequence[str], cwd: Optional[str]) -> bool:
    real = _real(path, cwd)
    for root in roots:
        try:
            if os.path.commonpath([root, real]) == root:
                return True
        except ValueError:
            # Different drives on Windows: simply not inside this root.
            continue
    return False


def _normalize_protected(paths: Optional[Iterable[str]]) -> frozenset:
    out = set()
    for path in paths or []:
        try:
            out.add(os.path.normcase(os.path.realpath(os.path.expanduser(path))))
        except Exception:
            continue
    return frozenset(out)


def _is_protected(path: str, protected: frozenset, cwd: Optional[str]) -> bool:
    return bool(protected) and os.path.normcase(_real(path, cwd)) in protected


def _protected_operand(
    name: str, paths: Sequence[str], protected: frozenset, cwd: Optional[str]
) -> Optional[str]:
    """The operand through which ``name`` would write a protected file, if any."""
    if not protected or not paths:
        return None
    if name in _DESTINATION_ONLY_COMMANDS:
        targets = paths[-1:] if len(paths) > 1 else []
    else:
        targets = paths
    for path in targets:
        if _is_protected(path, protected, cwd):
            return path
    if name in _INTO_DIRECTORY_COMMANDS and len(paths) > 1:
        dest = _real(paths[-1], cwd)
        if os.path.isdir(dest):
            for src in paths[:-1]:
                landed = os.path.join(dest, os.path.basename(src.rstrip("/\\")))
                if _is_protected(landed, protected, cwd):
                    return paths[-1]
    return None


def _deny_protected(path: str) -> Decision:
    return _deny(
        f"'{path}' controls what this Agent may run or reach (MCP servers, "
        f"permissions, config or credentials), so it can only be changed in "
        f"full-access mode. Nothing was written.",
        WORKSPACE_WRITE,
    )


def _roots_hint(roots: Sequence[str]) -> str:
    return ", ".join(roots[:2]) if roots else "the working directory"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def _switch_hint() -> str:
    """One line telling the model what to do, without a UI location that could
    mislead a channel user.

    The permission selector lives in the console — the desktop app or the Web
    console — so a user chatting through a channel (WeChat, Telegram, ...)
    cannot see anything "under the chat input". We name the console by build so
    the model can point the user to the right place, and keep it short.
    """
    where = "the desktop app" if os.environ.get("COW_DESKTOP") == "1" else "the Web console"
    return (
        f"To allow it, the user can change this session's permission in {where} "
        f"(or the global security setting). Do not retry the same call: use a "
        f"route the current mode allows, or tell the user which mode is needed."
    )


def _deny(what: str, mode: str) -> Decision:
    return Decision(False, f"Blocked by permission mode '{mode}': {what}\n\n{_switch_hint()}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def check_tool_call(
    mode: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
    write_roots: Optional[Iterable[str]] = None,
    protected_paths: Optional[Iterable[str]] = None,
) -> Decision:
    """Decide whether ``tool_name`` may run with ``arguments`` under ``mode``.

    Args:
        mode: one of :data:`MODES`; anything else is normalized.
        tool_name: the tool being called.
        arguments: the call's arguments (paths, commands, actions).
        cwd: working directory that relative paths resolve against.
        write_roots: directories writes are confined to in workspace-write mode.
            ``cwd`` and the system temp dir are always included.
        protected_paths: files workspace-write refuses even inside the roots.

    Returns:
        A :class:`Decision` whose ``reason`` is written for the model: what was
        refused, and what to do instead.
    """
    mode = normalize_mode(mode)
    if mode == FULL_ACCESS:
        return ALLOW

    tool_name = (tool_name or "").strip()
    args = arguments if isinstance(arguments, dict) else {}

    if mode == READ_ONLY:
        return _check_read_only(tool_name, args)
    return _check_workspace_write(tool_name, args, cwd, write_roots, protected_paths)


def _check_read_only(tool_name: str, args: Dict[str, Any]) -> Decision:
    if tool_name in _FILE_WRITE_TOOLS:
        path = str(args.get("path") or "")
        return _deny(
            f"this session cannot modify files, so {tool_name} did not run"
            + (f" (target: {path})" if path else "")
            + ". Nothing was written.",
            READ_ONLY,
        )

    if tool_name in _MUTATING_TOOLS:
        return _deny(f"{tool_name} changes state, which this session cannot do.", READ_ONLY)

    if tool_name in _ACTION_TOOLS:
        arg_name, mutating = _ACTION_TOOLS[tool_name]
        action = str(args.get(arg_name) or "").strip().lower()
        if action in mutating:
            return _deny(
                f"the {tool_name} action '{action}' changes state; its read-only "
                f"actions are still available.",
                READ_ONLY,
            )
        return ALLOW

    if tool_name == "bash":
        return _check_bash_read_only(args)

    if tool_name not in _KNOWN_TOOLS and _MUTATING_NAME_RE.search(tool_name):
        return _deny(
            f"'{tool_name}' looks like it changes state (judged from its name) and "
            f"this session is read-only.",
            READ_ONLY,
        )

    return ALLOW


def _check_workspace_write(
    tool_name: str,
    args: Dict[str, Any],
    cwd: Optional[str],
    write_roots: Optional[Iterable[str]],
    protected_paths: Optional[Iterable[str]] = None,
) -> Decision:
    roots = _normalize_roots(write_roots, cwd)
    protected = _normalize_protected(protected_paths)

    if tool_name in _FILE_WRITE_TOOLS:
        path = str(args.get("path") or "")
        if path and _is_protected(path, protected, cwd):
            return _deny_protected(path)
        if path and not _inside_roots(path, roots, cwd):
            return _deny(
                f"'{path}' is outside the writable area ({_roots_hint(roots)}), so "
                f"{tool_name} did not run and nothing was written. Reading it is "
                f"still allowed.",
                WORKSPACE_WRITE,
            )
        return ALLOW

    if tool_name == "bash":
        return _check_bash_workspace_write(args, cwd, roots, protected)

    return ALLOW


def _is_short_cluster(arg: str) -> bool:
    return len(arg) > 1 and arg[0] == "-" and arg[1] != "-"


def _xxd_output(args: Sequence[str]) -> List[str]:
    """xxd writes its second operand, or stdout when there is none."""
    operands = [a for i, a in enumerate(args) if not (i and args[i - 1] in _XXD_VALUE_FLAGS)]
    return _positional_paths(operands)[1:2]


def _read_only_write_form(
    name: str,
    args: Sequence[str],
) -> Optional[str]:
    """The flag or script form through which *name* writes a file, or None."""
    forms = _READ_ONLY_WRITE_FORMS.get(name, ())
    letters = _READ_ONLY_WRITE_SHORT.get(name, "")
    for arg in args:
        if any(arg == form or arg.startswith(form + "=") for form in forms):
            return arg
        if letters and _is_short_cluster(arg) and any(c in letters for c in arg[1:]):
            return arg

    if name == "sed":
        if any(_SED_WRITE_COMMAND_RE.search(a) for a in args if not a.startswith("-")):
            return "w"
    elif name == "xxd" and _xxd_output(args):
        return _xxd_output(args)[0]
    elif name == "awk" and any(_AWK_SHELL_RE.search(a) for a in args):
        return "system()"
    return None


def _check_bash_read_only(args: Dict[str, Any]) -> Decision:
    command = str(args.get("command") or "").strip()
    if not command:
        # Reading from or killing a background job the agent itself started.
        return ALLOW

    segments = _parse_segments(command)
    if segments is None:
        return _deny(
            "this command could not be parsed, and an unparsable command cannot be "
            "confirmed read-only.",
            READ_ONLY,
        )

    for tokens in segments:
        real_targets = [t for t in _redirect_targets(tokens) if t not in _NULL_SINKS]
        if real_targets:
            return _deny(
                f"the command redirects output into '{real_targets[0]}', which writes "
                f"a file.",
                READ_ONLY,
            )

        name, rest = _command_name(tokens)
        if name is None:
            continue
        if name in _ESCALATION_COMMANDS:
            return _deny(f"'{name}' escalates privileges.", READ_ONLY)
        if name == "git":
            decision = _check_git_read_only(rest)
            if not decision.allowed:
                return decision
            continue
        write_form = _read_only_write_form(name, rest)
        if write_form is not None:
            return _deny(
                f"'{name} {write_form}' writes a file without redirecting, so this "
                f"session cannot run it.",
                READ_ONLY,
            )
        if name not in _READ_ONLY_COMMANDS:
            return _deny(
                f"'{name}' is not on the read-only command allowlist, so it may change "
                f"something. Reading files (read / ls / search_files / grep) and "
                f"fetching pages (web_fetch / web_search) still work.",
                READ_ONLY,
            )
    return ALLOW


def _skip_git_global_options(args: Sequence[str]) -> Sequence[str]:
    """Drop git's leading global options (`-C dir`, `-c k=v`, `--no-pager`, ...)."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in _GIT_GLOBAL_VALUE_OPTIONS else 1
    return args[i:]


def _check_git_read_only(args: Sequence[str]) -> Decision:
    args = _skip_git_global_options(args)
    positional = [a for a in args if not a.startswith("-") and not _is_operator(a)]
    sub = positional[0].lower() if positional else ""
    if not sub:
        return ALLOW
    if sub not in _GIT_READ_SUBCOMMANDS:
        return _deny(f"'git {sub}' can change the repository.", READ_ONLY)
    if sub in _GIT_LIST_ONLY:
        second = positional[1].lower() if len(positional) > 1 else ""
        if second != _GIT_LIST_ONLY[sub]:
            return _deny(f"only 'git {sub} {_GIT_LIST_ONLY[sub]}' is read-only.", READ_ONLY)
        return ALLOW
    # The operand checks below only refuse; whatever passes them still has to
    # clear the write-flag check at the end (`git branch -v -D topic`).
    if sub in _GIT_LIST_OR_CREATE:
        listing = _GIT_LISTING_FLAGS | _GIT_EXTRA_LISTING_FLAGS.get(sub, frozenset())
        if len(positional) > 1 and not any(a in listing for a in args):
            return _deny(
                f"'git {sub} {positional[1]}' creates a {sub}, so it was refused. "
                f"Listing is read-only: 'git {sub}', or 'git {sub} -l <pattern>'.",
                READ_ONLY,
            )
    if sub == "remote":
        for verb in positional[1:]:
            if verb.lower() in _GIT_REMOTE_WRITE_VERBS:
                return _deny(
                    f"'git remote {verb}' changes the repository's remotes.",
                    READ_ONLY,
                )
    # A second operand makes symbolic-ref set the ref instead of reading it.
    if sub == "symbolic-ref" and len(positional) > 2:
        return _deny(
            f"'git symbolic-ref {positional[1]} {positional[2]}' sets the "
            "reference. Reading it is 'git symbolic-ref <ref>'.",
            READ_ONLY,
        )
    if sub == "config":
        if not any(a in _GIT_CONFIG_READ_FLAGS for a in args):
            return _deny("'git config' without --get/--list can write config.", READ_ONLY)
        return ALLOW
    write_flags = _GIT_WRITE_FLAGS | _GIT_BRANCH_WRITE_FLAGS if sub == "branch" else _GIT_WRITE_FLAGS
    offending = [a for a in args if a in write_flags]
    if offending:
        return _deny(f"'git {sub} {offending[0]}' modifies the repository.", READ_ONLY)
    return ALLOW


def _flag_destination(name: str, args: Sequence[str]) -> List[str]:
    """The paths a command writes when a flag names them instead of operands.

    ``cp -t DIR`` copies into DIR and ``unzip -d DIR`` extracts into DIR.
    ``tar`` writes the archive ``-f`` names when it creates one and the
    directory ``-C`` names when it extracts one.
    """
    if name == "tar":
        mode = ""
        for arg in args:
            if arg == "--":
                break
            if arg.startswith("--"):
                mode = _TAR_MODES.get(arg.split("=", 1)[0], mode)
                continue
            if arg.startswith("-") and len(arg) > 1:
                for letter in arg[1:]:
                    if letter in _TAR_VALUES:
                        break
                    mode = _TAR_MODES.get(letter, mode)
        if not mode:
            return []
        short = mode
        long = "--file" if mode == "f" else "--directory"
        stop = _TAR_VALUES
    else:
        spec = _FLAG_DESTINATIONS.get(name)
        if spec is None:
            return []
        short, long, stop = spec

    found = []
    for index, arg in enumerate(args):
        if arg == "--":
            break
        nxt = args[index + 1] if index + 1 < len(args) else None
        if arg.startswith("--"):
            key, sep, value = arg.partition("=")
            if long and key == long:
                found.append(value if sep else nxt)
        elif arg.startswith("-") and len(arg) > 1:
            cluster = arg[1:]
            for position, letter in enumerate(cluster):
                if letter == short:
                    found.append(cluster[position + 1:] or nxt)
                    break
                if letter in stop:
                    break
    return found


def _workspace_write_paths(name: str, args: Sequence[str]) -> List[str]:
    """Paths a path-mutating command writes, including flag-driven forms."""
    if name == "sort":
        paths = []
        for i, arg in enumerate(args):
            nxt = args[i + 1] if i + 1 < len(args) else ""
            if arg.startswith("--output"):
                paths.append(arg.split("=", 1)[1] if "=" in arg else nxt)
            elif _is_short_cluster(arg) and "o" in arg[1:]:
                paths.append(arg[arg.index("o", 1) + 1:] or nxt)
        return [p for p in paths if p]

    if name == "sed":
        # A `w` command names its destination inside the script text.
        found = [f.group(0).split()[1:]
                 for f in (_SED_WRITE_COMMAND_RE.search(a) for a in args
                           if not a.startswith("-")) if f]
        return found[0] if found else _positional_paths(args)

    if name == "xxd":
        return _xxd_output(args)

    if name in ("find", "fd", "awk"):
        # Their write forms act on whatever they match, so the search roots
        # must stay inside the workspace.
        if _read_only_write_form(name, args) is None:
            return []
        return _positional_paths(args)

    return _positional_paths(args)


def _check_bash_workspace_write(
    args: Dict[str, Any], cwd: Optional[str], roots: Sequence[str],
    protected: frozenset = frozenset(),
) -> Decision:
    command = str(args.get("command") or "").strip()
    if not command:
        return ALLOW

    segments = _parse_segments(command)
    if segments is None:
        # This mode is explicitly best effort, so an unparsable line goes to the
        # shell rather than blocking work that is probably fine.
        return ALLOW

    for tokens in segments:
        for target in _redirect_targets(tokens):
            if target in _NULL_SINKS:
                continue
            if _is_protected(target, protected, cwd):
                return _deny_protected(target)
            if not _inside_roots(target, roots, cwd):
                return _deny(
                    f"the command writes to '{target}', outside the writable area "
                    f"({_roots_hint(roots)}).",
                    WORKSPACE_WRITE,
                )

        name, rest = _command_name(tokens)
        if name is None:
            continue
        if name in _ESCALATION_COMMANDS:
            return _deny(f"'{name}' escalates privileges.", WORKSPACE_WRITE)
        if name not in _PATH_MUTATING_COMMANDS:
            continue
        if name == "sed" and _read_only_write_form(name, rest) is None:
            continue

        paths = _workspace_write_paths(name, rest)
        if name == "dd":
            paths = [a.split("=", 1)[1] for a in rest if a.startswith("of=")]
        hit = _protected_operand(name, paths, protected, cwd)
        if hit:
            return _deny_protected(hit)
        if name in _DESTINATION_ONLY_COMMANDS:
            paths = paths[-1:] if len(paths) > 1 else []

        for path in paths:
            if not path or path in _NULL_SINKS:
                continue
            if not _inside_roots(path, roots, cwd):
                return _deny(
                    f"'{name}' would change '{path}', outside the writable area "
                    f"({_roots_hint(roots)}). Reading it is still allowed.",
                    WORKSPACE_WRITE,
                )

        for destination in _flag_destination(name, rest):
            if not destination or destination in _NULL_SINKS:
                continue
            if _is_protected(destination, protected, cwd):
                return _deny_protected(destination)
            if not _inside_roots(destination, roots, cwd):
                return _deny(
                    f"'{name}' would change '{destination}', outside the writable area "
                    f"({_roots_hint(roots)}). Reading it is still allowed.",
                    WORKSPACE_WRITE,
                )
    return ALLOW


# ---------------------------------------------------------------------------
# Prompt text
# ---------------------------------------------------------------------------

def describe_mode(mode: str, language: str = "zh", cwd: Optional[str] = None) -> List[str]:
    """Prompt lines telling the model what it may change this session.

    Empty for full-access: with nothing gated there is nothing to say, and the
    historical prompt stays byte-identical.
    """
    mode = normalize_mode(mode)
    if mode == FULL_ACCESS:
        return []

    if language == "en":
        if mode == READ_ONLY:
            body = [
                "This session is **read-only**: you cannot modify files, and shell "
                "commands are limited to read-only utilities.",
                "",
                "- Investigating, reading and explaining are unaffected: `read`, `ls`, "
                "`search_files`, `web_search`, `web_fetch` and read-only shell "
                "commands all work.",
                "- Do not attempt writes. If the task needs them, say so and ask the "
                "user to switch this session's permission mode.",
            ]
        else:
            area = f"`{cwd}`" if cwd else "the working directory"
            body = [
                f"This session is **workspace-write**: you may freely create and change "
                f"files inside {area}.",
                "",
                "- Writes outside it are refused; reading anywhere is fine.",
                "- `mcp.json`, `config.json`, `.env` and the session settings files "
                "are not writable in this mode, even inside it.",
                "- If the task genuinely needs to write elsewhere, explain why and let "
                "the user switch the permission mode.",
            ]
        return ["## 🔐 Permissions", ""] + body + [""]

    if mode == READ_ONLY:
        body = [
            "当前会话为**只读模式**：不能修改任何文件，命令行也仅限只读类命令。",
            "",
            "- 查看、分析、解释都不受影响：`read`、`ls`、`search_files`、`web_search`、"
            "`web_fetch` 以及只读命令均可正常使用。",
            "- 不要尝试写入。如果任务确实需要写入，请说明原因并提示用户切换该会话的权限模式。",
        ]
    else:
        area = f"`{cwd}`" if cwd else "当前工作目录"
        body = [
            f"当前会话为**工作区可写模式**：可以在 {area} 内自由创建和修改文件。",
            "",
            "- 该目录之外的写入会被拒绝；读取不受限制。",
            "- `mcp.json`、`config.json`、`.env` 和会话设置文件在该模式下不可修改，即使位于该目录内。",
            "- 如果任务确实需要写到其他位置，请说明原因，由用户切换权限模式。",
        ]
    return ["## 🔐 权限", ""] + body + [""]
