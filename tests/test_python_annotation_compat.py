"""Shipped modules must stay importable on the oldest Python we advertise.

CI runs 3.11 and 3.13, but ``docs/guide/quick-start.mdx`` tells users Python
3.7-3.13 works (3.9 recommended) and ``pyproject.toml`` allows ``>=3.7``.
PEP 604 (``str | None``) and PEP 585 (``list[str]``) annotations are ordinary
syntax that parses on every version; they are only *evaluated* when the module
is imported, where they raise ``TypeError`` before 3.10 / 3.9 respectively.

That is how the built-in image-generation skill came to be unusable on the
recommended 3.9 interpreter while the whole suite stayed green: every CI
interpreter is new enough to evaluate its signatures. This guard inspects the
annotations Python actually evaluates (function signatures plus module- and
class-level annotated assignments) so the gap is caught without a 3.9 runner.
"""

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Dev-only trees: the test suite itself may use newer syntax, and these are
# neither imported nor executed by the running agent.
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "site-packages",
    "tests",
    "docs",
    "desktop",
    "mobile",
}

_BUILTIN_GENERICS = {"list", "dict", "tuple", "set", "frozenset", "type"}


def _has_postponed_annotations(tree):
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _evaluated_annotations(tree):
    """Yield annotations evaluated at import/definition time."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
                if arg is not None and arg.annotation is not None:
                    yield arg.annotation
            if node.returns is not None:
                yield node.returns

    def module_and_class_annotations(body):
        # Function bodies are never visited, so annotations on locals and
        # instance attributes (which Python does not evaluate) are not flagged.
        for node in body:
            if isinstance(node, ast.ClassDef):
                yield from module_and_class_annotations(node.body)
            elif isinstance(node, ast.AnnAssign):
                yield node.annotation

    yield from module_and_class_annotations(tree.body)


def _needs_newer_python(annotation):
    for node in ast.walk(annotation):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in _BUILTIN_GENERICS
        ):
            return True
    return False


def _candidate_sources():
    # Tracked files only: a checkout may hold ignored local trees (reference
    # code, scratch dirs) that are never shipped.
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=REPO_ROOT, capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return REPO_ROOT.rglob("*.py")
    return (REPO_ROOT / name for name in out.decode("utf-8").split("\0") if name)


def _shipped_sources():
    for path in _candidate_sources():
        if not path.is_file():
            continue
        parts = path.relative_to(REPO_ROOT).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        yield path


def test_shipped_annotations_are_postponed_or_old_python_safe():
    offenders = []
    for path in _shipped_sources():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        if _has_postponed_annotations(tree):
            continue
        for annotation in _evaluated_annotations(tree):
            if _needs_newer_python(annotation):
                offenders.append(
                    "{}:{}: {}".format(
                        path.relative_to(REPO_ROOT), annotation.lineno, ast.unparse(annotation)
                    )
                )

    assert offenders == [], (
        "Annotations are evaluated at import time and raise TypeError on the "
        "advertised Python 3.7-3.9. Add `from __future__ import annotations` "
        "(or use typing.List/Optional): " + "; ".join(offenders)
    )
