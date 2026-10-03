"""
Artifact detection - decide which agent-written files are user-facing outputs.

The agent writes many files that are internal bookkeeping (memory logs, skills,
knowledge base pages). Only files a human would actually want to open should be
surfaced in the chat UI as previewable artifacts.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

from common.log import logger
from common.utils import expand_path

# Directories under the workspace that hold agent-internal state, never artifacts.
INTERNAL_DIRS = {
    "memory",
    "knowledge",
    "skills",
    "tmp",
    "scheduler",
}

# Workspace-root files that are part of the agent's own configuration.
INTERNAL_FILES = {
    "AGENT.md",
    "RULE.md",
    "MEMORY.md",
    "USER.md",
    "BOOTSTRAP.md",
    "mcp.json",
}

_EXT_KINDS = {
    "html": {".html", ".htm"},
    "markdown": {".md", ".markdown"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico"},
    "video": {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"},
    "pdf": {".pdf"},
    "csv": {".csv", ".tsv"},
    "code": {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".go",
        ".rs", ".rb", ".php", ".sh", ".sql", ".css", ".scss", ".json", ".yaml",
        ".yml", ".xml", ".toml", ".ini",
    },
    "text": {".txt", ".log"},
    "office": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"},
}

# Kinds the frontend can render inline in the preview panel.
PREVIEWABLE_KINDS = {
    "html", "markdown", "image", "video", "audio", "pdf", "csv", "code", "text",
}

# Kinds whose bytes are plain text, so the preview panel can offer an editor.
# Deliberately a subset of PREVIEWABLE_KINDS: an image or a PDF previews fine
# but would be destroyed by a round-trip through a text area.
EDITABLE_KINDS = {"html", "markdown", "csv", "code", "text"}

_KIND_BY_EXT: Dict[str, str] = {
    ext: kind for kind, exts in _EXT_KINDS.items() for ext in exts
}


def get_workspace_root() -> str:
    """Absolute path of the routed Agent's workspace."""
    from common.state_dir import real_state_root

    return real_state_root()


def classify_kind(path: str) -> str:
    """Map a file extension to a coarse preview kind."""
    ext = os.path.splitext(path)[1].lower()
    return _KIND_BY_EXT.get(ext, "file")


def is_previewable(kind: str) -> bool:
    return kind in PREVIEWABLE_KINDS


def is_editable(kind: str) -> bool:
    return kind in EDITABLE_KINDS


def resolve_workspace_path(path: str, workspace_root: str) -> str:
    """Resolve a tool `path` argument the same way the file tools do."""
    expanded = expand_path(path)
    if os.path.isabs(expanded):
        return os.path.realpath(expanded)
    return os.path.realpath(os.path.join(workspace_root, expanded))


def _is_internal(abs_path: str, workspace_root: str) -> bool:
    """True when the file is agent bookkeeping rather than a user-facing output."""
    name = os.path.basename(abs_path)
    if name.startswith("."):
        return True

    try:
        rel = os.path.relpath(abs_path, workspace_root)
    except ValueError:
        # Different drive on Windows: outside the workspace, judge by name only.
        return False

    if rel.startswith(".."):
        # Outside the workspace (e.g. editing project source): not an artifact.
        return True

    parts = rel.split(os.sep)
    if len(parts) == 1:
        return name in INTERNAL_FILES
    if parts[0] in INTERNAL_DIRS:
        return True
    return any(p.startswith(".") for p in parts[:-1])


def build_artifact(path: str, workspace_root: Optional[str] = None) -> Optional[Dict]:
    """
    Build artifact metadata for a file the agent just wrote.

    Returns None when the file is internal, missing, or not worth surfacing.
    """
    if not path:
        return None

    root = workspace_root or get_workspace_root()
    # resolve_workspace_path() realpath-resolves the file (following symlinks),
    # so the root must be resolved the same way or the relpath check below sees
    # a mismatched prefix (e.g. /var vs /private/var on macOS) and wrongly treats
    # an in-project file as "outside the workspace".
    try:
        root = os.path.realpath(expand_path(root))
    except Exception:
        pass
    try:
        abs_path = resolve_workspace_path(path, root)
    except Exception:
        return None

    if _is_internal(abs_path, root):
        return None
    return _describe(abs_path, root)


def build_sent_artifact(path: str, workspace_root: Optional[str] = None) -> Optional[Dict]:
    """Artifact metadata for a file delivered with `send`.

    Sending is a deliberate delivery, so the workspace-internal filter does not
    apply: a screenshot under tmp/ that was sent is still something the user got.
    """
    if not path or path.lower().startswith(("http://", "https://")):
        return None
    root = workspace_root or get_workspace_root()
    try:
        root = os.path.realpath(expand_path(root))
        abs_path = resolve_workspace_path(path, root)
    except Exception:
        return None
    if os.path.basename(abs_path).startswith("."):
        return None
    return _describe(abs_path, root)


def _describe(abs_path: str, root: str) -> Optional[Dict]:
    if not os.path.isfile(abs_path):
        return None

    try:
        size = os.path.getsize(abs_path)
    except OSError:
        size = 0

    try:
        # POSIX on every platform, like the memory index keys: a Windows
        # separator makes the same file read as a different path.
        rel_path = os.path.relpath(abs_path, root).replace(os.sep, "/")
    except ValueError:
        rel_path = abs_path
    if rel_path.startswith(".."):
        rel_path = abs_path

    kind = classify_kind(abs_path)
    return {
        "type": "artifact",
        "path": abs_path,
        "rel_path": rel_path,
        "dir": os.path.dirname(abs_path),
        "file_name": os.path.basename(abs_path),
        "kind": kind,
        "previewable": is_previewable(kind),
        "size": size,
    }


def safe_build_artifact(path: str, workspace_root: Optional[str] = None) -> Optional[Dict]:
    """build_artifact that never raises - artifact reporting must not break a tool call."""
    try:
        return build_artifact(path, workspace_root)
    except Exception as e:
        logger.debug(f"[Artifact] skipped {path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Files changed by a shell command
# ---------------------------------------------------------------------------

# Kinds a shell command is credited with when it changes a file it names.
# Source, logs and data files are left out: commands rewrite those constantly
# while building or debugging, and none of that is a deliverable.
_COMMAND_KINDS = ("html", "markdown", "image", "video", "audio", "pdf", "csv", "office")
_COMMAND_EXTS = sorted(
    {ext[1:] for kind in _COMMAND_KINDS for ext in _EXT_KINDS[kind]},
    key=len, reverse=True,
)
_COMMAND_PATH_STOP = r"""\s'"`<>|;&()=,{}\[\]（）【】「」《》“”‘’，、：；"""
_COMMAND_PATH_RE = re.compile(
    r"[^%s]*[^%s/\\]\.(?:%s)(?![\w.])"
    % (_COMMAND_PATH_STOP, _COMMAND_PATH_STOP, "|".join(_COMMAND_EXTS)),
    re.IGNORECASE,
)
_CD_RE = re.compile(r"""(?:^|[;&|(\n])\s*cd\s+("[^"]+"|'[^']+'|[^\s;&|)]+)""")
_COMMAND_FILES_KEY = "files_written"
_COMMAND_FILES_RE = re.compile(r'"%s"\s*:\s*(\[[^\]]*\])' % _COMMAND_FILES_KEY)
_COMMAND_FILES_MAX = 20
_COMMAND_TOKENS_MAX = 60


def _command_candidates(command: str, cwd: str) -> List[str]:
    """Every path a file named in the command could refer to: as written when
    absolute, else under the working dir and under each ``cd`` target."""
    if not command or not cwd:
        return []
    bases = [cwd]
    for match in _CD_RE.finditer(command):
        target = expand_path(match.group(1).strip("'\""))
        bases.append(target if os.path.isabs(target) else os.path.join(cwd, target))
    out: List[str] = []
    for token in _COMMAND_PATH_RE.findall(command)[:_COMMAND_TOKENS_MAX]:
        token = expand_path(token)
        for path in [token] if os.path.isabs(token) else [os.path.join(b, token) for b in bases]:
            path = os.path.normpath(path)
            if path not in out:
                out.append(path)
    return out


def _file_signature(path: str) -> Optional[tuple]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not os.path.isfile(path):
        return None
    return (st.st_mtime_ns, st.st_size)


def snapshot_command_files(command: str, cwd: str) -> Dict[str, Optional[tuple]]:
    """State of the files a command names, taken before it runs."""
    return {p: _file_signature(p) for p in _command_candidates(command, cwd)}


def files_changed_by_command(command: str, cwd: str, before: Dict[str, Optional[tuple]]) -> List[str]:
    """User-facing files a shell command named and created or modified.

    A command's effects can't be traced, so this settles for the files it
    mentions, compared against ``before`` (see snapshot_command_files). Only
    user-facing files under ``cwd`` count; backups to /tmp and the like don't.
    """
    found: List[str] = []
    for path in _command_candidates(command, cwd):
        sig = _file_signature(path)
        if sig is None or before.get(path) == sig:
            continue
        real = os.path.realpath(path)
        if real not in found and safe_build_artifact(real, cwd):
            found.append(real)
            if len(found) >= _COMMAND_FILES_MAX:
                break
    return found


def command_files_from_result(raw: Any) -> List[str]:
    """Paths a stored `bash` result reports under ``files_written``.

    Falls back to a pattern match because history trimming may have cut the
    JSON short; the key is written first so it survives a truncated tail.
    """
    data = _result_json(raw)
    if isinstance(data, dict):
        files = data.get(_COMMAND_FILES_KEY)
    else:
        match = _COMMAND_FILES_RE.search(raw) if isinstance(raw, str) else None
        try:
            files = json.loads(match.group(1)) if match else None
        except ValueError:
            files = None
    if not isinstance(files, list):
        return []
    return [str(p) for p in files if isinstance(p, str) and p]


# ---------------------------------------------------------------------------
# Artifact index: what a stored stretch of conversation produced
# ---------------------------------------------------------------------------

# Images, video and audio the agent embedded in its reply. Generated media is
# often shown this way rather than written by a file tool.
_MD_MEDIA_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_EMBED_KINDS = {"image", "video", "audio"}


def _result_json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return None


def _tool_results(messages: List[Dict]) -> Dict[str, Dict]:
    """tool_use_id -> {"content": str, "is_error": bool} for every result."""
    results: Dict[str, Dict] = {}
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            body = block.get("content", "")
            if isinstance(body, list):
                body = "\n".join(
                    b.get("text", "") for b in body
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            results[block.get("tool_use_id", "")] = {
                "content": body if isinstance(body, str) else str(body),
                "is_error": bool(block.get("is_error")),
            }
    return results


def collect_message_artifacts(messages: List[Dict], workspace_root: str) -> List[Dict]:
    """User-facing files produced by a list of stored (LLM-format) messages.

    Covers files written by `write`/`edit`, those a `bash` command or a
    `subagent` reports, files delivered with `send`, and media embedded in the
    reply text. Every entry is
    an existing file: ``{"path", "kind", "size", "source"}``, deduplicated.
    """
    if not messages or not workspace_root:
        return []
    root = os.path.realpath(expand_path(workspace_root))
    results = _tool_results(messages)
    found: Dict[str, Dict] = {}

    def add(info: Optional[Dict], source: str) -> None:
        if not info or info["path"] in found:
            return
        found[info["path"]] = {
            "path": info["path"],
            "kind": info.get("kind", "file"),
            "size": info.get("size", 0),
            "source": source,
        }

    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                for ref in _MD_MEDIA_RE.findall(block.get("text") or ""):
                    if "://" in ref or ref.startswith(("/api/", "/preview/", "data:")):
                        continue
                    info = safe_build_artifact(ref, root)
                    if info and info["kind"] in _EMBED_KINDS:
                        add(info, "embed")
                continue
            if btype != "tool_use":
                continue
            name = block.get("name")
            args = block.get("input") if isinstance(block.get("input"), dict) else {}
            result = results.get(block.get("id", ""))
            if result and result["is_error"]:
                continue
            try:
                if name in ("write", "edit"):
                    data = _result_json(result["content"]) if result else None
                    path = (data.get("path") if isinstance(data, dict) else None) or args.get("path")
                    add(safe_build_artifact(str(path or ""), root), name)
                elif name == "send":
                    data = _result_json(result["content"]) if result else None
                    path = (data.get("path") if isinstance(data, dict) else None) or args.get("path")
                    add(build_sent_artifact(str(path or "").strip(), root), "send")
                elif name == "bash" and result:
                    for path in command_files_from_result(result["content"]):
                        add(safe_build_artifact(path, root), "bash")
                elif name == "subagent" and result:
                    data = _result_json(result["content"])
                    items = data.get("results") if isinstance(data, dict) else None
                    for item in items or []:
                        if isinstance(item, dict):
                            for path in item.get("files") or []:
                                add(safe_build_artifact(str(path), root), "subagent")
            except Exception as e:
                logger.debug(f"[Artifact] index skipped a {name} call: {e}")
    return list(found.values())


def artifact_root_for(
    session_id: str,
    agent_id: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> str:
    """The directory a session's file tools resolve paths against: the project
    it has open, else the Agent's workspace."""
    if session_id:
        try:
            from agent.workspace import project_store
            project_dir = project_store.get_project_dir(session_id, agent_id)
            if project_dir:
                return project_dir
        except Exception:
            pass
    if workspace_root:
        return workspace_root
    try:
        from agent.registry import get_agent_registry
        return get_agent_registry().get(agent_id, require_enabled=False).workspace
    except Exception:
        return get_workspace_root()


def index_message_artifacts(
    store,
    session_id: str,
    messages: List[Dict],
    workspace_root: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> None:
    """Record what newly stored messages produced. Never raises."""
    if not session_id or not messages:
        return
    try:
        root = artifact_root_for(session_id, agent_id, workspace_root)
        items = collect_message_artifacts(messages, root)
        if items:
            store.record_artifacts(session_id, items)
    except Exception as e:
        logger.debug(f"[Artifact] index failed for session={session_id}: {e}")
