"""Guest page actions for a front end on the control connection.

That front end renders the pages, authenticates its visitors and enforces its
own access rules (passwords, embedding sites, per-address limits). On every
request it names the profile, the visitor and the conversation; from there
the same share, store and runtime calls as the console and the /share pages
take over, so confinement, limits and storage are unchanged.

The connection is authenticated, so owner actions here carry the console's
trust: ``upsert`` confirms what it writes, as saving in the console does.
Widenings the main Agent writes to a profile on disk still wait for
``confirm``. Paths in every response are virtual.

``dispatch`` never raises: refusals come back as ``code`` with
``payload.reason``.
"""

from __future__ import annotations

import base64
import dataclasses
import mimetypes
import os
import re
import time
from typing import Any, Callable, Dict, Optional

from agent.guest import share as share_mod
from agent.guest import store
from agent.guest.paths import MENTION_RE, WORK
from agent.guest.profile import (
    DATA_DIR,
    DEFAULT_TOOLS,
    LANGUAGES,
    LIMIT_SPECS,
    TOOL_CATALOG,
    delete_profile,
    ensure_guests_readme,
    is_valid_slug,
    list_slugs,
)
from agent.guest.runtime import GuestError, available_skills, get_service, reference_suggestions
from common.log import logger

ChunkSink = Callable[[Dict[str, Any]], None]

_VISITOR_RE = re.compile(rf"^[0-9a-f]{{{store.VISITOR_ID_LEN}}}$")
_SESSION_RE = re.compile(r"^[0-9a-f]{1,64}$")
# Each file chunk is base64 in one line-delimited message; keep it well
# under common frame limits.
DEFAULT_CHUNK_BYTES = 768 * 1024
MAX_CHUNK_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
UPLOAD_TIMEOUT_SECONDS = 60


def dispatch(action: str, payload: Optional[Dict[str, Any]], send_chunk: Optional[ChunkSink] = None) -> dict:
    """Run one action. ``send_chunk`` receives a ``message`` turn's progress."""
    payload = payload if isinstance(payload, dict) else {}
    if action != "message" and action not in _ACTIONS:
        return _result(action, 404, f"Unknown action: {action}", {"reason": "unknown_action"})
    try:
        if action == "message":
            return _result(action, 200, "", _message(payload, send_chunk))
        return _result(action, 200, "", _ACTIONS[action](payload))
    except GuestError as e:
        return _result(action, e.code, e.message, {"reason": e.reason})
    except Exception as e:
        logger.error(f"[GuestShare] Action {action} failed: {e}", exc_info=True)
        return _result(action, 500, "Internal error.", {"reason": "internal_error"})


def _result(action: str, code: int, message: str, payload: Any) -> dict:
    return {"action": action, "code": code, "message": message, "payload": payload}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --- owner side --------------------------------------------------------------


def _slug(payload: Dict[str, Any]) -> str:
    slug = str(payload.get("slug") or "").strip()
    if slug == DATA_DIR or not is_valid_slug(slug):
        raise GuestError(400, "Invalid profile id.", "invalid_slug")
    return slug


def _state(payload: Dict[str, Any]):
    state = share_mod.resolve(_slug(payload))
    if state is None:
        raise GuestError(404, "Profile not found.", "share_not_found")
    return state


def _view(state, detail: bool = False) -> Dict[str, Any]:
    data = share_mod.describe(state)
    if detail:
        data["raw_config"] = state.profile.config
        data["guest_md"] = state.profile.guest_md
    return data


def _options(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tools": list(TOOL_CATALOG),
        "default_tools": list(DEFAULT_TOOLS),
        "limits": {key: {"min": low, "max": high, "default": default}
                   for key, (low, high, default) in LIMIT_SPECS.items()},
        "languages": list(LANGUAGES),
        "skills": available_skills(),
        "references": reference_suggestions(),
    }


def _upsert(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = _slug(payload)
    config = payload.get("config")
    if not isinstance(config, dict):
        raise GuestError(400, "config must be an object.", "invalid_config")
    guest_md = payload.get("guest_md") if isinstance(payload.get("guest_md"), str) else None
    ensure_guests_readme()
    return _view(share_mod.save_and_confirm(slug, config, guest_md), detail=True)


def _get(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = _state(payload)
    view = _view(state, detail=True)
    view["questions_today"] = store.questions_today(state.slug)
    view["tokens_today"] = store.tokens_today(state.slug)
    return view


def _list(payload: Dict[str, Any]) -> Dict[str, Any]:
    shares = []
    for slug in list_slugs():
        state = share_mod.resolve(slug)
        if state is not None:
            shares.append(_view(state))
    return {"shares": shares}


def _confirm(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = _state(payload)
    return _view(share_mod.confirm_current(state.slug) or state, detail=True)


def _disable(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = _state(payload).slug
    store.update_entry(slug, disabled=True)
    get_service().forget_profile(slug)
    return _view(_state(payload), detail=True)


def _enable(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = _state(payload).slug
    store.update_entry(slug, disabled=False)
    return _view(_state(payload), detail=True)


def _delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = _state(payload).slug
    get_service().forget_profile(slug)
    store.purge(slug)
    delete_profile(slug)
    return {}


def _logs(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = _state(payload).slug
    limit = max(1, min(_int(payload.get("limit"), 200), 500))
    return {"sessions": store.list_sessions(slug, limit)}


def _log_detail(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = _state(payload).slug
    session_id = str(payload.get("session_id") or "")
    if not _SESSION_RE.match(session_id):
        raise GuestError(404, "Conversation not found.", "session_not_found")
    return {"records": store.read_messages(slug, session_id, 2000)}


# --- visitor side ------------------------------------------------------------


def _visitor(payload: Dict[str, Any], require_active: bool = True):
    """The profile, visitor and conversation a request names, if the
    conversation is that visitor's and still theirs to use."""
    state = _state(payload)
    if require_active and not state.active:
        raise GuestError(403, "This page is not available right now.", state.status)
    visitor_id = str(payload.get("visitor_id") or "")
    session_id = str(payload.get("session_id") or "")
    if (not _VISITOR_RE.match(visitor_id) or not _SESSION_RE.match(session_id)
            or not store.owns_session(visitor_id, session_id) or store.is_deleted(state.slug, session_id)):
        raise GuestError(404, "Conversation not found.", "session_not_found")
    return state, visitor_id, session_id


def _message(payload: Dict[str, Any], send_chunk: Optional[ChunkSink]) -> Dict[str, Any]:
    state, visitor_id, session_id = _visitor(payload)
    attachments = payload.get("attachments")
    attachments = [a for a in attachments if isinstance(a, str)] if isinstance(attachments, list) else []
    service = get_service()
    turn = service.begin(state, visitor_id, session_id, str(payload.get("text") or ""), attachments)
    if send_chunk is not None:
        try:
            send_chunk({"type": "stream_start", "request_id": turn.id})
        except Exception as e:
            logger.warning(f"[GuestShare] Event handler failed: {e}")
    return dataclasses.asdict(service.execute(turn, on_event=send_chunk))


def _cancel(payload: Dict[str, Any]) -> Dict[str, Any]:
    state, _, session_id = _visitor(payload, require_active=False)
    return {"cancelled": get_service().cancel(state.slug, session_id)}


def _clear(payload: Dict[str, Any]) -> Dict[str, Any]:
    state, visitor_id, session_id = _visitor(payload)
    get_service().clear_context(state, visitor_id, session_id)
    return {}


def _upload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch a file the front end has put at ``url`` into the conversation."""
    state, _, session_id = _visitor(payload)
    url = str(payload.get("url") or "").strip()
    if not url:
        raise GuestError(400, "No file URL.", "invalid_url")
    limits = (state.effective or {}).get("limits") or {}
    content = _download(url, int(limits.get("max_upload_mb") or 20) * 1024 * 1024)
    name = str(payload.get("name") or "") or os.path.basename(url.split("?", 1)[0]) or "file"
    vpath = get_service().save_upload(state, session_id, name, content)
    is_image = (mimetypes.guess_type(vpath)[0] or "").startswith("image/")
    return {"path": vpath, "name": os.path.basename(vpath), "size": len(content),
            "file_type": "image" if is_image else "file"}


def _download(url: str, max_bytes: int) -> bytes:
    """Public addresses only, every redirect re-checked, the size counted on
    what is actually read."""
    import requests

    from agent.tools.utils.url_safety import safe_get, strict_url_guard, validate_url_safe

    deadline = time.monotonic() + UPLOAD_TIMEOUT_SECONDS
    with strict_url_guard():
        try:
            validate_url_safe(url)
            response = safe_get(url, timeout=30, stream=True)
        except ValueError:
            raise GuestError(400, "This file URL is not allowed.", "url_blocked")
        except requests.RequestException:
            raise GuestError(502, "Could not fetch the file.", "fetch_failed")
    with response:
        if response.status_code != 200:
            raise GuestError(502, "Could not fetch the file.", "fetch_failed")
        chunks, total = [], 0
        try:
            for chunk in response.iter_content(64 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise GuestError(413, "File is too large.", "too_large")
                if time.monotonic() > deadline:
                    raise GuestError(504, "Fetching the file took too long.", "fetch_timeout")
                chunks.append(chunk)
        except requests.RequestException:
            raise GuestError(502, "Could not fetch the file.", "fetch_failed")
    return b"".join(chunks)


def _offered(state, session_id: str, vpath: str) -> bool:
    """Whether the visitor may download ``vpath``: anything in the
    conversation's own /work, else only a file one of its replies sent or
    mentioned, the same files the /share pages sign links for."""
    if vpath.startswith(WORK + "/"):
        return True
    for record in store.read_messages(state.slug, session_id, 2000):
        if record.get("role") != "assistant":
            continue
        if any(f.get("path") == vpath for f in record.get("files") or []):
            return True
        texts = [record.get("content") or ""] + [s.get("content") or "" for s in record.get("steps") or []
                                                  if s.get("type") == "content"]
        for text in texts:
            if any(m.group(0).rstrip(".,;:!?") == vpath for m in MENTION_RE.finditer(text)):
                return True
    return False


def _file(payload: Dict[str, Any]) -> Dict[str, Any]:
    """One base64 chunk of a file; callers pull offsets until ``eof``."""
    state, _, session_id = _visitor(payload)
    service = get_service()
    real = service.local_file(state, session_id, str(payload.get("path") or ""))
    vpath = service.guard_for(state, session_id).virtual_of(real) if real else None
    if not vpath or not _offered(state, session_id, vpath):
        raise GuestError(404, "File not found.", "file_not_found")
    size = os.path.getsize(real)
    if size > MAX_FILE_BYTES:
        raise GuestError(413, "File is too large.", "too_large")
    offset = max(0, _int(payload.get("offset"), 0))
    chunk_size = max(1, min(_int(payload.get("chunk_size"), DEFAULT_CHUNK_BYTES), MAX_CHUNK_BYTES))
    with open(real, "rb") as f:
        f.seek(offset)
        raw = f.read(chunk_size)
    return {
        "path": vpath,
        "name": os.path.basename(real),
        "mime": mimetypes.guess_type(real)[0] or "application/octet-stream",
        "total_size": size,
        "offset": offset,
        "length": len(raw),
        "eof": offset + len(raw) >= size,
        "content_b64": base64.b64encode(raw).decode("ascii"),
    }


_ACTIONS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "options": _options,
    "upsert": _upsert,
    "get": _get,
    "list": _list,
    "confirm": _confirm,
    "disable": _disable,
    "enable": _enable,
    "delete": _delete,
    "logs": _logs,
    "log_detail": _log_detail,
    "cancel": _cancel,
    "clear": _clear,
    "upload": _upload,
    "file": _file,
}
