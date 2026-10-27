"""The tools a visitor's Agent is given.

Each one wraps a built-in tool behind the session's PathGuard: path arguments
are virtual paths resolved (and refused) before the built-in tool sees them,
and whatever the tool returns has real paths turned back into virtual ones.
The built-in tool only ever receives an absolute path the guard already
approved, so none of its own fallbacks (relative paths, ``~``, the shared
knowledge lookup) can reach past the mounts.
"""

from __future__ import annotations

import copy
import mimetypes
import os
import posixpath
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from agent.guest.paths import WORK, GuestPathError, PathGuard
from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger

_PATH_HINT = (
    "Relative paths resolve under /work. Available: /work (this conversation's files, writable; "
    "uploads are in /work/uploads), /data/<name> and /skills/<name> (read-only)."
)

# Attributes the agent loop sets on a tool before each call.
_CALL_ATTRS = ("model", "context", "cancel_event", "progress_callback", "event_callback", "tool_call_id")


def _with_path_hint(params: dict, keys: List[str]) -> dict:
    params = copy.deepcopy(params or {})
    props = params.get("properties") or {}
    for key in keys:
        if key in props:
            props[key]["description"] = f"Path of the file or directory. {_PATH_HINT}"
    return params


class GuestTool(BaseTool):
    """A built-in tool confined to the session's mounts."""

    def __init__(self, inner: BaseTool, guard: PathGuard, path_keys: List[str],
                 write: bool = False, max_work_bytes: Optional[int] = None):
        self.inner = inner
        self.guard = guard
        self.path_keys = path_keys
        self.write = write
        self.max_work_bytes = max_work_bytes
        self.name = inner.name
        self.description = inner.description
        self.params = _with_path_hint(inner.params, path_keys)
        self.cwd = guard.work_dir

    def is_available(self) -> bool:
        try:
            return bool(self.inner.is_available())
        except Exception:
            return True

    def _forward_call_state(self) -> None:
        for attr in _CALL_ATTRS:
            setattr(self.inner, attr, getattr(self, attr, None))

    def _map_args(self, params: Dict[str, Any]) -> Dict[str, Any]:
        args = dict(params or {})
        if self.name == "read" and not args.get("path") and args.get("location"):
            args["path"] = args.pop("location")
        args.pop("location", None)
        for key in self.path_keys:
            value = args.get(key)
            if value in (None, ""):
                continue
            args[key] = self.guard.resolve(str(value), write=self.write)
        return args

    def _check_quota(self, args: Dict[str, Any]) -> Optional[str]:
        if not self.write or not self.max_work_bytes:
            return None
        incoming = len(str(args.get("content") or args.get("newText") or "").encode("utf-8"))
        if self.guard.work_usage_bytes() + incoming > self.max_work_bytes:
            return "Error: this conversation's storage is full; no more files can be written."
        return None

    def _rewrite(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.guard.to_virtual(value)
        if isinstance(value, dict):
            return {k: self._rewrite(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._rewrite(v) for v in value]
        return value

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            args = self._map_args(params)
        except GuestPathError as e:
            return ToolResult.fail(f"Error: {e}")
        quota_error = self._check_quota(args)
        if quota_error:
            return ToolResult.fail(quota_error)
        self._forward_call_state()
        try:
            result = self.inner.execute_tool(args)
        finally:
            for attr in _CALL_ATTRS:
                if attr != "model":
                    setattr(self.inner, attr, None)
        return ToolResult(
            status=result.status,
            result=self._rewrite(result.result),
            ext_data=None,
            display=self._rewrite(result.display) if result.display else None,
        )


class GuestSearchFiles(GuestTool):
    """search_files whose hits are checked one by one: the backends walk the
    tree themselves, and some open symlinked or hard-linked files that the
    guard refuses when they are named directly."""

    def __init__(self, inner: BaseTool, guard: PathGuard):
        super().__init__(inner, guard, path_keys=["path"])

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            vroot = self.guard.to_vpath(str((params or {}).get("path") or WORK))
            root_is_dir = os.path.isdir(self.guard.resolve(vroot))
        except GuestPathError:
            vroot, root_is_dir = None, False
        result = super().execute(params)
        if result.status != "success" or not root_is_dir or not isinstance(result.result, dict):
            return result
        payload = dict(result.result)
        removed = 0
        for key in ("matches", "counts", "files"):
            rows = payload.get(key)
            if not isinstance(rows, list):
                continue
            kept = []
            for row in rows:
                name = row if key == "files" else (row.get("file") if isinstance(row, dict) else None)
                if self._allowed(vroot, name):
                    kept.append(row)
                elif key == "counts":
                    removed += int(row.get("count") or 0)
                else:
                    removed += 1
            payload[key] = kept
        if removed and isinstance(payload.get("match_count"), int):
            payload["match_count"] = max(payload["match_count"] - removed, 0)
        return ToolResult(status=result.status, result=payload, ext_data=None, display=result.display)

    def _allowed(self, vroot: str, name: Any) -> bool:
        if not isinstance(name, str) or not name:
            return False
        name = name.replace("\\", "/")
        vpath = name if name.startswith("/") else posixpath.join(vroot, name)
        try:
            self.guard.resolve(vpath)
        except GuestPathError:
            return False
        return True


class GuestWebFetch(GuestTool):
    """web_fetch with SSRF protection forced on and the profile's domain allowlist."""

    def __init__(self, inner: BaseTool, guard: PathGuard, allow_domains: List[str],
                 max_work_bytes: Optional[int] = None):
        super().__init__(inner, guard, path_keys=[], max_work_bytes=max_work_bytes)
        self.allow_domains = list(allow_domains or [])

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        from agent.tools.utils.url_safety import host_allowed, strict_url_guard

        url = str((params or {}).get("url") or "").strip()
        host = urlparse(url).hostname or ""
        if self.allow_domains and not host_allowed(host, self.allow_domains):
            return ToolResult.fail(f"Error: {host or url} is not an allowed domain for this page.")
        # Documents are downloaded into /work/tmp, so a full work dir stops fetching.
        if self.max_work_bytes and self.guard.work_usage_bytes() >= self.max_work_bytes:
            return ToolResult.fail("Error: this conversation's storage is full; no more files can be downloaded.")
        with strict_url_guard(self.allow_domains):
            return super().execute(params)


def _is_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


class GuestVision(GuestTool):
    """vision on a file in the mounts, or on an image URL when the page may
    reach the network, under the same rules as web_fetch."""

    def __init__(self, inner: BaseTool, guard: PathGuard, network: Dict[str, Any]):
        super().__init__(inner, guard, path_keys=["image"])
        self.network_enabled = bool(network.get("enabled"))
        self.allow_domains = list(network.get("allow_domains") or [])

    def _map_args(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if _is_url(str((params or {}).get("image") or "").strip()):
            return dict(params or {})
        return super()._map_args(params)

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        from agent.tools.utils.url_safety import host_allowed, strict_url_guard

        image = str((params or {}).get("image") or "").strip()
        if _is_url(image):
            if not self.network_enabled:
                return ToolResult.fail("Error: images from the web are not available here; use an uploaded file.")
            host = urlparse(image).hostname or ""
            if self.allow_domains and not host_allowed(host, self.allow_domains):
                return ToolResult.fail(f"Error: {host or image} is not an allowed domain for this page.")
            with strict_url_guard(self.allow_domains):
                result = super().execute(params)
        else:
            result = super().execute(params)
        # The stock message tells the model how to configure API keys.
        if result.status != "success" and "No model available for Vision" in str(result.result):
            return ToolResult.fail("Error: image understanding is not available on this page.")
        return result


class GuestSend(BaseTool):
    """Offer a file to the visitor. Only files the visitor could read anyway."""

    name = "send"
    description = (
        "Send a file to the visitor as a download (images are shown inline). "
        "Use it for files you created under /work or material they may have."
    )
    params = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": f"Path of the file to send. {_PATH_HINT}"},
            "message": {"type": "string", "description": "Optional message to accompany the file"},
        },
        "required": ["path"],
    }

    def __init__(self, guard: PathGuard):
        self.guard = guard
        self.cwd = guard.work_dir

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        raw = str((params or {}).get("path") or "").strip()
        if raw.lower().startswith(("http://", "https://")):
            return ToolResult.fail("Error: put URLs directly in your reply instead of sending them.")
        try:
            real = self.guard.resolve(raw)
        except GuestPathError as e:
            return ToolResult.fail(f"Error: {e}")
        if not os.path.isfile(real):
            return ToolResult.fail(f"Error: File not found: {raw}")
        vpath = self.guard.virtual_of(real) or self.guard.to_vpath(raw)
        mime = mimetypes.guess_type(real)[0] or "application/octet-stream"
        if mime.startswith("image/"):
            file_type = "image"
        elif mime.startswith("video/"):
            file_type = "video"
        elif mime.startswith("audio/"):
            file_type = "audio"
        else:
            file_type = "file"
        name = os.path.basename(real)
        return ToolResult.success({
            "type": "file_to_send",
            "file_type": file_type,
            "path": vpath,
            "file_name": name,
            "mime_type": mime,
            "size": os.path.getsize(real),
            "message": (params or {}).get("message") or f"Sent {name}",
        })


def build_guest_tools(config: Dict[str, Any], guard: PathGuard) -> List[BaseTool]:
    """Instantiate the tools ``config`` offers, each confined by ``guard``."""
    from agent.guest.policy import offered_tools

    names = offered_tools(config)
    max_work = int((config.get("limits") or {}).get("max_work_mb") or 0) * 1024 * 1024 or None
    base = {"cwd": guard.work_dir}
    tools: List[BaseTool] = []
    for name in names:
        try:
            if name == "read":
                from agent.tools.read.read import Read
                tools.append(GuestTool(Read(dict(base)), guard, ["path"]))
            elif name == "ls":
                from agent.tools.ls.ls import Ls
                tools.append(GuestTool(Ls(dict(base)), guard, ["path"]))
            elif name == "search_files":
                from agent.tools.search_files.search_files import SearchFiles
                tools.append(GuestSearchFiles(SearchFiles(dict(base)), guard))
            elif name == "write":
                from agent.tools.write.write import Write
                tools.append(GuestTool(Write(dict(base)), guard, ["path"], write=True, max_work_bytes=max_work))
            elif name == "edit":
                from agent.tools.edit.edit import Edit
                tools.append(GuestTool(Edit(dict(base)), guard, ["path"], write=True, max_work_bytes=max_work))
            elif name == "send":
                tools.append(GuestSend(guard))
            elif name == "time":
                from agent.tools.current_time.current_time import TimeTool
                tools.append(GuestTool(TimeTool(), guard, []))
            elif name == "web_search":
                from agent.tools.web_search.web_search import WebSearch
                tools.append(GuestTool(WebSearch(), guard, []))
            elif name == "web_fetch":
                from agent.tools.web_fetch.web_fetch import WebFetch
                domains = (config.get("network") or {}).get("allow_domains") or []
                tools.append(GuestWebFetch(WebFetch(dict(base)), guard, domains, max_work_bytes=max_work))
            elif name == "vision":
                from agent.tools.vision.vision import Vision
                tools.append(GuestVision(Vision(dict(base)), guard, config.get("network") or {}))
        except Exception as e:
            logger.warning(f"[GuestShare] Tool {name} unavailable: {e}")
    return tools


__all__ = ["GuestTool", "GuestSearchFiles", "GuestWebFetch", "GuestVision", "GuestSend", "build_guest_tools", "WORK"]
