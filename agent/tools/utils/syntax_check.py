"""
Cheap, in-process syntax validation for files the agent writes.

The agent has no compiler, test runner or language server to tell it that an
edit broke a file, so a mistake can sit unnoticed until something tries to load
the file much later. Parsing what we are about to write costs a millisecond and
catches the most common self-inflicted damage: truncated generation, mashed
quotes, a replacement pasted at the wrong indentation.

Two tiers, split by whether "does not parse" is ever a legitimate state:

* Structured data (JSON/YAML/TOML) is an atomic blob - half a JSON document is
  never something anyone meant to write, so a parse failure blocks the write.
* Source code can legitimately be mid-construction, so it only ever produces a
  warning.

Either way only breakage the edit *introduced* counts: a file that was already
unparseable stays quiet.
"""

import ast
import json
import os
import re
from typing import Optional, Tuple

# Extensions whose content is an atomic structured blob: refuse to write when
# it does not parse.
BLOCKING_EXTS = frozenset({'.json', '.yaml', '.yml', '.toml'})

# A JSON string (group 1, kept as is), or a comment / trailing comma outside of
# one - so "https://..." or "@/*" inside a string is never taken for a comment.
_JSON_STRING = r'("(?:\\.|[^"\\])*")'
_JSONC_COMMENT = re.compile(_JSON_STRING + r'|//[^\n]*|/\*.*?\*/', re.DOTALL)
_JSONC_TRAILING_COMMA = re.compile(_JSON_STRING + r'|,(?=\s*[\]}])')

# Go template syntax, the language of Helm charts: whitespace trimming
# ({{- ... -}}) or a field or variable reference ({{ .Values.x }}, {{ $name }}).
# Plain {{ item.name }} Jinja (Ansible, Home Assistant) and GitHub's ${{ }} do
# not match, so a broken one of those files is still refused.
_GO_TEMPLATE = re.compile(r'\{\{-|-\}\}|\{\{(?:[^{}]*?[\s(])?[.$]\w')


def _check_json(text: str) -> Optional[str]:
    try:
        json.loads(text)
    except ValueError as e:
        return str(e)
    return None


def _blank(match: re.Match) -> str:
    # Keep strings; space out comments and trailing commas rather than drop
    # them, so error positions still match the file.
    return match.group(1) or re.sub(r'[^\n]', ' ', match.group())


def _check_jsonc(text: str) -> Optional[str]:
    """JSON with comments and trailing commas, as TypeScript and VS Code read it."""
    text = _JSONC_COMMENT.sub(_blank, text)
    return _check_json(_JSONC_TRAILING_COMMA.sub(_blank, text))


def _is_jsonc(path: str) -> bool:
    """Whether this .json file is read as JSON with comments.

    Only well-known names: anywhere else a comment is a real error - npm
    rejects one in package.json, and so does CowAgent in its own config.json.
    """
    name = os.path.basename(path).lower()
    return (
        name.startswith(('tsconfig', 'jsconfig'))
        or name in ('devcontainer.json', '.devcontainer.json')
        or os.path.basename(os.path.dirname(path)).lower() == '.vscode'
    )


def _check_yaml(text: str) -> Optional[str]:
    try:
        import yaml
    except ImportError:
        return None
    try:
        # parse(), not safe_load(): we want a syntax verdict, and safe_load
        # additionally rejects perfectly well-formed YAML that uses tags the
        # loader does not know about.
        for _ in yaml.parse(text):
            pass
    except Exception as e:
        if _GO_TEMPLATE.search(text):
            # A Helm chart template is only YAML once rendered, so a parse
            # failure says nothing about it.
            return None
        return str(e).replace('\n', ' ')
    return None


def _check_toml(text: str) -> Optional[str]:
    try:
        import tomllib
    except ImportError:
        return None
    try:
        tomllib.loads(text)
    except Exception as e:
        return str(e)
    return None


def _check_python(text: str) -> Optional[str]:
    try:
        ast.parse(text)
    except SyntaxError as e:
        where = f" (line {e.lineno})" if e.lineno else ""
        return f"{e.msg}{where}"
    except ValueError as e:
        # e.g. source containing null bytes
        return str(e)
    return None


_CHECKERS = {
    '.json': _check_json,
    '.yaml': _check_yaml,
    '.yml': _check_yaml,
    '.toml': _check_toml,
    '.py': _check_python,
}


def check(path: str, text: str) -> Optional[str]:
    """Return a syntax error message for *text*, or None if it is fine.

    None is also returned for file types we cannot check, so callers can treat
    "no error" and "not checked" the same way.
    """
    ext = os.path.splitext(path)[1].lower()
    checker = _check_jsonc if ext == '.json' and _is_jsonc(path) else _CHECKERS.get(ext)
    if checker is None:
        return None
    try:
        return checker(text)
    except Exception:
        # A checker blowing up must never stop the agent from writing a file.
        return None


def is_blocking(path: str) -> bool:
    """Whether a parse failure for this path should refuse the write."""
    return os.path.splitext(path)[1].lower() in BLOCKING_EXTS


def review(path: str, old_text: Optional[str], new_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Judge a pending write of *new_text* over *old_text*.

    :return: (blocking_error, warning) - at most one is set.
    """
    error = check(path, new_text)
    if error is None:
        return None, None

    # Stay quiet unless this change is what broke it. A file that was already
    # unparseable is mid-construction or not really this format (say, JSON with
    # comments under a name we do not know): refusing would lock the agent out
    # of it, and a warning would fire on every routine step.
    if old_text is not None and check(path, old_text) is not None:
        return None, None

    if is_blocking(path):
        return (
            f"Refusing to write {os.path.basename(path)}: the content is not valid "
            f"{os.path.splitext(path)[1].lstrip('.').upper()} ({error}). "
            f"The file was left unchanged - fix the content and retry."
        ), None

    return None, (
        f"This edit leaves {os.path.basename(path)} with a syntax error: {error}. "
        f"The write was applied - re-read the file and fix it if that was not intended."
    )
