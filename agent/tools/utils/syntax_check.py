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
  warning, and only when the edit *introduced* the breakage (a file that was
  already unparseable stays quiet).
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
# Only looked for in YAML under a templates/ directory, where Helm keeps them,
# or in a file that already failed to parse because of them.
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

    Only well-known names, plus any file that already has comments (see
    _pick_checker): in a strict JSON file a comment is a real error - npm
    rejects one in package.json, and so does CowAgent in its own config.json.
    """
    name = os.path.basename(path).lower()
    return (
        name.startswith(('tsconfig', 'jsconfig'))
        or name in ('devcontainer.json', '.devcontainer.json', '.eslintrc.json')
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
        return str(e).replace('\n', ' ')
    return None


def _is_helm_template(path: str) -> bool:
    """Whether this YAML file sits in a templates/ directory, the only place
    Helm renders chart templates from."""
    return 'templates' in os.path.normpath(os.path.dirname(path)).lower().split(os.sep)


def _check_helm_template(text: str) -> Optional[str]:
    error = _check_yaml(text)
    if error and _GO_TEMPLATE.search(text):
        # A Helm chart template is only YAML once rendered, so a parse
        # failure says nothing about it.
        return None
    return error


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


# The lenient reading of a format whose own tools accept more than the strict
# parser does: JSON with comments, YAML with template actions.
_LENIENT_CHECKERS = {
    '.json': _check_jsonc,
    '.yaml': _check_helm_template,
    '.yml': _check_helm_template,
}


def _run(checker, text: str) -> Optional[str]:
    try:
        return checker(text)
    except Exception:
        # A checker blowing up must never stop the agent from writing a file.
        return None


def _pick_checker(path: str, old_text: Optional[str]):
    ext = os.path.splitext(path)[1].lower()
    strict = _CHECKERS.get(ext)
    lenient = _LENIENT_CHECKERS.get(ext)
    if lenient is None:
        return strict
    if _is_jsonc(path) if ext == '.json' else _is_helm_template(path):
        return lenient
    # A file that already relies on the lenient form under a name we do not
    # know (VS Code user settings, wrangler.json, a chart kept outside
    # templates/) is read that way by its own tool: keep checking it that way
    # rather than lock the agent out of it.
    if old_text and _run(strict, old_text) is not None and _run(lenient, old_text) is None:
        return lenient
    return strict


def check(path: str, text: str, old_text: Optional[str] = None) -> Optional[str]:
    """Return a syntax error message for *text*, or None if it is fine.

    *old_text* is the current content of the file, if any: a file that already
    uses comments or template actions keeps being checked leniently.

    None is also returned for file types we cannot check, so callers can treat
    "no error" and "not checked" the same way.
    """
    checker = _pick_checker(path, old_text)
    if checker is None:
        return None
    return _run(checker, text)


def is_blocking(path: str) -> bool:
    """Whether a parse failure for this path should refuse the write."""
    return os.path.splitext(path)[1].lower() in BLOCKING_EXTS


def review(path: str, old_text: Optional[str], new_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Judge a pending write of *new_text* over *old_text*.

    :return: (blocking_error, warning) - at most one is set.
    """
    error = check(path, new_text, old_text)
    if error is None:
        return None, None

    if is_blocking(path):
        ext = os.path.splitext(path)[1].lower()
        hint = ""
        if ext == '.json' and _run(_check_jsonc, new_text) is None:
            hint = " This file is strict JSON: comments and trailing commas are not allowed."
        return (
            f"Refusing to write {os.path.basename(path)}: the content is not valid "
            f"{ext.lstrip('.').upper()} ({error}).{hint} "
            f"The file was left unchanged - fix the content and retry."
        ), None

    # Source code: stay quiet unless this change is what broke it. A file that
    # was already unparseable is either mid-construction or not really source,
    # and warning there would fire on every routine step.
    if old_text is not None and check(path, old_text) is not None:
        return None, None

    return None, (
        f"This edit leaves {os.path.basename(path)} with a syntax error: {error}. "
        f"The write was applied - re-read the file and fix it if that was not intended."
    )
