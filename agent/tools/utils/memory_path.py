"""
Which written files feed the memory index.

`MemoryManager.sync()` only re-runs when the manager is dirty, so a write the
tools fail to report here stays invisible to retrieval until the next restart.
Over-reporting costs one hash-based re-scan; under-reporting costs the agent
knowledge it just wrote down, so the checks below err towards reporting.
"""

import os

# Trees and files MemoryManager.sync() scans, relative to the workspace root.
INDEXED_DIRS = ("memory", "knowledge")
INDEXED_FILES = ("MEMORY.md",)


def _real(path: str) -> str:
    return os.path.normpath(os.path.realpath(os.path.expanduser(str(path))))


def _relative(target: str, base: str) -> str:
    """``target`` as a path relative to ``base``, or "" if it sits outside."""
    try:
        rel = os.path.relpath(target, _real(base))
    except ValueError:
        return ""  # different drive on Windows
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return ""
    return rel


def _workspace_root(memory_manager) -> str:
    config = getattr(memory_manager, "config", None)
    return getattr(config, "workspace_root", None) or ""


def _shared_knowledge_dir(workspace_root: str) -> str:
    """Where knowledge writes land for an Agent without a ``knowledge/`` of its
    own: outside its workspace, so the segment check cannot see them."""
    if not workspace_root:
        return ""
    try:
        from common import state_dir

        return str(state_dir.knowledge_dir(base=workspace_root))
    except Exception:
        # No resolvable shared root (registry not ready). The workspace still
        # covers every file that is not a shared fallback.
        return ""


def indexes_rel_path(rel_path: str) -> bool:
    """Whether a path relative to a scanned root feeds the index.

    The relative form of :func:`feeds_memory_index`, for callers that already
    hold a path relative to the root it was resolved against -- the console's
    file editor, which saves workspace-relative paths. Both forms read the same
    ``INDEXED_DIRS`` / ``INDEXED_FILES``, so an indexed tree is declared once.

    They were separate, and drifted: the console kept matching ``memory/`` and
    ``MEMORY.md`` while this module added ``knowledge/``, so a knowledge page
    saved from the console stopped re-embedding while the same write through a
    tool still did (#3176). A backslash separator is normalized where it is one
    (Windows); elsewhere it is an ordinary character in a file name.
    """
    text = str(rel_path or "")
    if os.sep == "\\":
        text = text.replace("\\", "/")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or parts[0] == os.pardir:
        return False
    if len(parts) == 1 and parts[0] in INDEXED_FILES:
        return True
    return parts[0] in INDEXED_DIRS


def feeds_memory_index(absolute_path: str, memory_manager, cwd: str = "") -> bool:
    """Whether writing ``absolute_path`` should mark the memory index dirty.

    Decided by resolving the path and comparing segments against the workspace,
    rather than testing the raw argument for ``"memory/"``. That test missed
    ``knowledge/`` entirely, so knowledge writes left the index stale (#3176);
    missed Windows separators (``memory\\note.md``); and matched any path merely
    containing the fragment, such as ``src/memory/cache.py``.

    The tool's ``cwd`` is checked besides the memory workspace because a session
    bound to a project retargets cwd there while memory stays in the workspace.
    """
    target = _real(absolute_path)
    workspace_root = _workspace_root(memory_manager)

    for base in (workspace_root, cwd):
        if not base:
            continue
        rel = _relative(target, base)
        if rel and indexes_rel_path(rel):
            return True

    shared_knowledge = _shared_knowledge_dir(workspace_root)
    return bool(shared_knowledge and _relative(target, shared_knowledge))
