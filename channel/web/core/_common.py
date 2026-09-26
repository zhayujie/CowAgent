"""Shared plumbing behind the web console.

What both sides of the channel need: the request-scoped helpers (auth, the
agent a request is addressed to, upload and workspace paths), the small value
types, and the module-level state that has to be one object per process.

It lives here because ``WebChannel`` and the request handlers both reach for
it. Nothing in this module knows about a handler or about the channel, so it
can be imported from either without a cycle -- which is the whole point:
before, the handlers and the channel had to share a module to share a helper.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import quote

import web

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.channel_registry import get_channel_manager
from common.log import logger
from config import conf, get_data_root, read_config_template


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".avi", ".mov", ".mkv"}

# Cap for a file the desktop client asks us to import by path. Matches the
# multipart body cap on the HTTP server so both upload routes agree.
MAX_LOCAL_IMPORT_BYTES = 512 * 1024 * 1024


def _is_loopback_request() -> bool:
    """True when the current request came straight from this machine.

    A request that went through a reverse proxy carries forwarding headers even
    if the proxy itself sits on localhost, so those disqualify it.
    """
    env = getattr(web.ctx, "env", {}) or {}
    if env.get("HTTP_X_FORWARDED_FOR") or env.get("HTTP_X_REAL_IP"):
        return False
    addr = (env.get("REMOTE_ADDR") or "").strip()
    return addr in ("::1", "::ffff:127.0.0.1") or addr.startswith("127.")


def _desktop_token_matches() -> bool:
    """Whether the request carries the secret the desktop shell handed us.

    The shell generates a random token per launch and passes it in via
    COW_DESKTOP_TOKEN when it spawns the backend, then sends it back on its own
    requests. A browser tab talking to the same port never sees the env of the
    process, so it can't forge this; a source run without the shell has no
    token, and the check simply fails closed.
    """
    expected = os.environ.get("COW_DESKTOP_TOKEN", "")
    if not expected:
        return False
    env = getattr(web.ctx, "env", {}) or {}
    provided = env.get("HTTP_X_COW_DESKTOP_TOKEN", "")
    return bool(provided) and hmac.compare_digest(provided, expected)


@dataclass
class SSEStreamState:
    """Bounded, replayable event log for one web request."""

    condition: threading.Condition = field(default_factory=threading.Condition)
    events: deque = field(default_factory=deque)
    next_seq: int = 1
    total_bytes: int = 0
    last_active: float = field(default_factory=time.time)
    main_done: bool = False
    main_done_at: Optional[float] = None
    stream_complete: bool = False
    completed_at: Optional[float] = None
    closed: bool = False
    # Where the stored transcript and this log last lined up: messages up to
    # ``stored_seq`` hold exactly what events up to ``stored_event_seq`` showed.
    stored_seq: Optional[int] = None
    stored_event_seq: int = 0


def _read_config_file_for_write() -> dict:
    """Baseline dict for a partial write to config.json.

    When the file does not exist yet (fresh install), seed from
    config-template.json — the very config the running process loaded. Starting
    from an empty dict would persist a file missing every template default
    (model, agent limits, ...), silently changing behavior after a restart.
    """
    config_path = os.path.join(get_data_root(), "config.json")
    if os.path.exists(config_path):
        # utf-8-sig tolerates a UTF-8 BOM (common when the file was edited with
        # Windows Notepad / PowerShell). Plain utf-8 would raise "Unexpected
        # UTF-8 BOM" here and fail every config write from the web console.
        with open(config_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return read_config_template()


def _write_config_file_for_write(config_path: str, data: dict) -> None:
    """Write ``data`` to ``config_path`` without truncating the old file first.

    Every console save reads config.json, changes a few keys and writes the whole
    dict back. Writing straight into ``config_path`` truncates it before the new
    bytes are there, so anything that fails while serialising -- a value json
    cannot encode, a full disk, the process being killed -- leaves a half-written
    file. That is worse here than for a cache: ``load_config`` treats an
    unparseable user config as corruption, and on the desktop client the self-heal
    path quarantines the file and replaces it with config-template.json, so every
    API key, channel credential and custom provider goes with it. A source
    deployment instead raises and never starts. Building the result beside the
    file and replacing it means a failed save leaves whatever was there before.
    """
    tmp_path = f"{config_path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, config_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def _get_web_password() -> str:
    # Coerce to str so non-string values in config.json (e.g. numeric password) won't break comparisons
    pwd = conf().get("web_password", "")
    if pwd is None:
        return ""
    return str(pwd)


def _is_password_enabled():
    return bool(_get_web_password())


# Set once the console owns its socket. The desktop watchdog waits on this to
# tell "still starting" apart from "wedged and never going to answer".
SERVING = threading.Event()

_BIND_ERROR_CODE_RE = re.compile(r"\[(WinError|Errno) (\d+)\]")


def _bind_error_codes(err: OSError):
    """Return ``(winerror, errno)`` for a bind failure.

    cheroot swallows the original exception: it re-raises a bare
    ``socket.error(msg)`` with neither errno nor ``__cause__`` set, so on the
    path we actually care about the code only survives inside the message text.
    """
    winerror = getattr(err, "winerror", None)
    err_no = err.errno
    if winerror is None and err_no is None:
        for kind, code in _BIND_ERROR_CODE_RE.findall(str(err)):
            if kind == "WinError":
                winerror = int(code)
            else:
                err_no = int(code)
    return winerror, err_no


def _log_bind_failure(host: str, port: int, err: OSError):
    """Explain a failed bind in terms the user can act on.

    Windows needs its own branch: a port can be permanently unbindable because
    Hyper-V/WSL2/Docker reserved the range it falls in (WinError 10013), and
    nothing is listening on it, so the usual "kill the stale process" advice
    sends people looking for a process that doesn't exist.
    """
    winerror, err_no = _bind_error_codes(err)
    if winerror == 10013:
        logger.error(
            f"[WebChannel] 端口 {port} 被系统保留，无法绑定（WinError 10013）。"
            f"通常是 Hyper-V/WSL2/Docker 占用了该端口段，可执行 "
            f"`netsh interface ipv4 show excludedportrange protocol=tcp` 查看，"
            f"或在 config.json 中把 web_port 改成区间外的端口"
        )
    elif winerror == 10048 or err_no in (48, 98):  # WSAEADDRINUSE / macOS / Linux
        logger.error(
            f"[WebChannel] 端口 {port} 已被占用，可执行 `cow restart` 清理残留进程，"
            f"或在 config.json 中修改 web_port"
        )
    else:
        logger.error(f"[WebChannel] 无法在 {host}:{port} 上启动服务: {err}")


def _session_expire_seconds():
    return int(conf().get("web_session_expire_days", 30)) * 86400


def _verify_auth_token(token):
    """Verify a signed token is valid and not expired.

    The token is derived from the password, so it survives server restarts
    and automatically invalidates when the password changes.
    """
    if not token or "." not in token:
        return False
    ts_hex, sig = token.split(".", 1)
    try:
        ts = int(ts_hex, 16)
    except ValueError:
        return False
    if time.time() - ts > _session_expire_seconds():
        return False
    expected = hmac.new(
        _get_web_password().encode(),
        ts_hex.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


def _get_bearer_token():
    """Extract the token from an `Authorization: Bearer <token>` header.

    The desktop client renders from a file:// origin, so cross-origin cookies
    to http://127.0.0.1 are unreliable (SameSite=Lax cookies aren't sent). It
    therefore authenticates via this header instead; browsers keep using the
    cookie set by /auth/login.
    """
    auth = web.ctx.env.get("HTTP_AUTHORIZATION", "") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def _get_query_token():
    """Extract a token from the `token` query param.

    Needed for SSE endpoints: EventSource can't set an Authorization header,
    and file:// cookies are unreliable, so the desktop client passes the token
    in the query string for /stream and /api/logs.
    """
    try:
        return web.input(token="").token or ""
    except Exception:
        return ""


def _check_auth():
    """Return True if request is authenticated or password not enabled."""
    if not _is_password_enabled():
        return True
    if _verify_auth_token(web.cookies().get("cow_auth_token", "")):
        return True
    if _verify_auth_token(_get_bearer_token()):
        return True
    return _verify_auth_token(_get_query_token())


def _require_auth():
    """Raise 401 if not authenticated. Call at the top of protected handlers."""
    if not _check_auth():
        # Log which credential the caller offered (never the value). A rejected
        # request is otherwise invisible in run.log, which makes client bugs —
        # e.g. an endpoint that forgets the Authorization header — undiagnosable.
        offered = []
        if web.cookies().get("cow_auth_token", ""):
            offered.append("cookie")
        if _get_bearer_token():
            offered.append("bearer")
        if _get_query_token():
            offered.append("query")
        logger.warning(
            "[WebChannel] 401 Unauthorized: %s %s (credentials offered: %s)",
            web.ctx.env.get("REQUEST_METHOD", "?"),
            web.ctx.env.get("PATH_INFO", "?"),
            ", ".join(offered) or "none",
        )
        raise web.HTTPError("401 Unauthorized",
                            {"Content-Type": "application/json; charset=utf-8"},
                            json.dumps({"status": "error", "message": "Unauthorized"}))


# Localized text for /cancel system replies. Web is the only channel that
# honors a per-request `lang`; other channels reply in Chinese by default.
def _cancel_reply_text(cancelled: int, lang: str) -> str:
    en = lang.startswith("en")
    if cancelled > 0:
        return "🛑 Cancelled" if en else "🛑 已中止"
    return "Nothing to cancel." if en else "当前没有可中止的任务。"


def _steer_reply_text(status, lang: str) -> str:
    from agent.protocol import SteerStatus

    en = (lang or "").lower().startswith("en")
    messages = {
        SteerStatus.ACCEPTED: (
            "↪️ Active task redirected.", "↪️ 已引导当前任务。"
        ),
        SteerStatus.INACTIVE: (
            "No active task to steer.", "当前没有可引导的任务。"
        ),
        SteerStatus.CLOSING: (
            "The active task is already finishing.", "当前任务已结束，无法再引导。"
        ),
        SteerStatus.AMBIGUOUS: (
            "Multiple tasks are active in this session; the steering target is ambiguous.",
            "当前会话有多个任务在运行，无法确定引导目标。",
        ),
        SteerStatus.FULL: (
            "Too many steering updates are pending; try again after the agent processes them.",
            "引导指令过多，请等待当前任务处理后再试。",
        ),
        SteerStatus.INVALID: (
            "Usage: /steer <instruction>", "用法：/steer <引导指令>"
        ),
    }
    english, chinese = messages[status]
    return english if en else chinese


def _get_upload_dir(agent_id: str = None) -> str:
    from agent.registry import get_agent_registry

    workspace = get_agent_registry().get(agent_id).workspace
    upload_dir = os.path.join(workspace, "tmp")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _get_workspace_root(session_id: str = None, agent_id: str = None) -> str:
    """Resolve the working directory for this request.

    When a session has opened a project directory, that project is the working
    directory the file panel / preview / ``@`` picker operate in. Otherwise it
    is the Agent's workspace (``state_root``, e.g. ``~/cow``). Memory and skills
    always stay in ``state_root`` regardless; only the working root moves.
    """
    if session_id:
        try:
            from agent.workspace import project_store
            project_dir = project_store.get_project_dir(session_id, agent_id)
            if project_dir:
                return project_dir
        except Exception as e:
            logger.debug(f"[WebChannel] project_dir resolve failed: {e}")
    from agent.registry import get_agent_registry

    return get_agent_registry().get(agent_id).workspace


_PREVIEW_SECRET = None
_PREVIEW_SECRET_LOCK = threading.Lock()


def _get_preview_secret() -> bytes:
    """
    Stable secret used to sign /preview directory tokens.

    Preview URLs can't rely on the auth cookie: the preview iframe is sandboxed
    without `allow-same-origin`, so its subresource requests come from an opaque
    origin and Chrome withholds the SameSite=Lax cookie. The signature in the
    URL is what authorizes the request instead, so it must survive restarts.
    """
    global _PREVIEW_SECRET
    if _PREVIEW_SECRET is not None:
        return _PREVIEW_SECRET
    with _PREVIEW_SECRET_LOCK:
        if _PREVIEW_SECRET is not None:
            return _PREVIEW_SECRET
        path = os.path.join(get_data_root(), ".preview_secret")
        secret = None
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    secret = (f.read() or "").strip() or None
        except Exception as e:
            logger.warning(f"[WebChannel] Could not read preview secret: {e}")
        if not secret:
            secret = uuid.uuid4().hex + uuid.uuid4().hex
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(secret)
                os.chmod(path, 0o600)
            except Exception as e:
                logger.warning(f"[WebChannel] Could not persist preview secret: {e}")
        _PREVIEW_SECRET = secret.encode()
        return _PREVIEW_SECRET


def _encode_dir_token(dir_path: str) -> str:
    """Encode a directory path into a signed, URL-safe token for /preview."""
    real = os.path.realpath(dir_path)
    body = base64.urlsafe_b64encode(real.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(_get_preview_secret(), real.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"{body}.{sig}"


def _build_preview_url(abs_path: str) -> str:
    """
    Preview URL that mounts the file's *directory*, so relative assets
    referenced by an HTML page (./style.css, ./img/a.png) resolve correctly.
    """
    directory = os.path.dirname(abs_path)
    name = os.path.basename(abs_path)
    return f"/preview/{_encode_dir_token(directory)}/{quote(name)}"


# Media links the agent embeds in its reply markdown are workspace-relative
# (e.g. `images/x.png`, saved under the agent workspace by the image/video
# skills). The browser would resolve those against the console URL and 404,
# so they only render for the default agent whose workspace happens to match
# the serve root. Rewriting them to an absolute /api/file URL makes them load
# for every agent. Only *relative* refs are touched — absolute paths, http(s)
# URLs, file:// and already-routed /api or /preview links are left untouched,
# so nothing that worked before (including the default agent) changes.
_MD_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)(\s*(?:\"[^\"]*\")?\s*\))")
_HTML_IMG_SRC_RE = re.compile(r"(<img\b[^>]*?\bsrc=[\"'])([^\"']+)([\"'])", re.IGNORECASE)


def _is_relative_media_ref(ref: str) -> bool:
    """True for a workspace-relative media ref that needs absolutizing."""
    if not ref:
        return False
    ref = ref.strip()
    # Scheme (http, https, data, file, mailto), protocol-relative, site-absolute
    # (/api/file, /preview), home (~) or Windows drive paths all resolve on their
    # own — leave them alone.
    if re.match(r"^[a-zA-Z][\w+.-]*:", ref):
        return False
    if ref.startswith(("//", "/", "~")):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", ref):
        return False
    return True


def _rewrite_relative_media(content: str, workspace_root: str) -> str:
    """Rewrite workspace-relative media refs in markdown/HTML to /api/file URLs.

    ``workspace_root`` is the absolute root the relative refs are anchored to
    (the agent's workspace, or the open project dir). Refs that escape the root
    or don't resolve to an existing file are left untouched, so this never turns
    a harmless relative link into a broken absolute one.
    """
    if not content or not workspace_root:
        return content
    root_real = os.path.realpath(workspace_root)

    def _to_api_url(ref: str) -> Optional[str]:
        if not _is_relative_media_ref(ref):
            return None
        rel = ref.split("?", 1)[0].split("#", 1)[0]
        abs_path = os.path.realpath(os.path.join(root_real, rel))
        # Confine to the workspace root: a ref like `../../etc/passwd` must not
        # be turned into a servable URL.
        try:
            if os.path.commonpath([abs_path, root_real]) != root_real:
                return None
        except ValueError:
            return None
        if not os.path.isfile(abs_path):
            return None
        return f"/api/file?path={quote(abs_path)}"

    def _md_repl(m: re.Match) -> str:
        url = _to_api_url(m.group(2))
        return f"{m.group(1)}{url}{m.group(3)}" if url else m.group(0)

    def _img_repl(m: re.Match) -> str:
        url = _to_api_url(m.group(2))
        return f"{m.group(1)}{url}{m.group(3)}" if url else m.group(0)

    out = _MD_IMAGE_RE.sub(_md_repl, content)
    out = _HTML_IMG_SRC_RE.sub(_img_repl, out)
    return out


def _build_artifact_payload(data: dict) -> dict:
    """Turn an agent `artifact` event into an SSE payload for the web clients."""
    file_path = data.get("path", "")
    if not file_path:
        return None
    return {
        "type": "artifact",
        "abs_path": file_path,
        "rel_path": data.get("rel_path") or os.path.basename(file_path),
        "file_name": data.get("file_name") or os.path.basename(file_path),
        "kind": data.get("kind", "file"),
        "previewable": bool(data.get("previewable")),
        "size": data.get("size", 0),
        "raw_url": f"/api/file?path={quote(file_path)}",
        "preview_url": _build_preview_url(file_path),
    }


def _sanitize_upload_relative_path(relative_path: str) -> str:
    """Normalize relative upload path and reject escapes / absolute paths."""
    relative_path = (relative_path or "").replace("\\", "/").strip("/")
    if not relative_path:
        raise ValueError("Empty relative path")
    parts = []
    for part in relative_path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("Invalid relative path")
        parts.append(part)
    if not parts:
        raise ValueError("Invalid relative path")
    norm_path = "/".join(parts)
    if os.path.isabs(norm_path):
        raise ValueError("Invalid relative path")
    return norm_path


def _sanitize_upload_id(upload_id: str) -> str:
    """Allow only simple batch ids for directory uploads."""
    sanitized = "".join(ch for ch in (upload_id or "") if ch.isalnum() or ch in ("-", "_"))
    if not sanitized:
        raise ValueError("Invalid upload id")
    return sanitized[:80]


def _is_within_directory(root_path: str, target_path: str) -> bool:
    try:
        return os.path.commonpath([root_path, target_path]) == root_path
    except ValueError:
        return False


def _resolve_upload_path(upload_root: str, relative_path: str) -> Tuple[str, str]:
    """Resolve a relative upload path under upload_root and reject escapes."""
    safe_rel_path = _sanitize_upload_relative_path(relative_path)
    upload_root_real = os.path.realpath(upload_root)
    save_path = os.path.realpath(os.path.join(upload_root_real, *safe_rel_path.split("/")))
    if not _is_within_directory(upload_root_real, save_path):
        raise ValueError("Invalid directory upload path")
    return safe_rel_path, save_path


def _read_uploaded_file_bytes(file_obj) -> bytes:
    """Return uploaded content as bytes across web.py upload object variants."""
    if isinstance(file_obj, bytes):
        return file_obj
    if isinstance(file_obj, str):
        return file_obj.encode("utf-8")

    content = None

    if hasattr(file_obj, "file") and hasattr(file_obj.file, "read"):
        content = file_obj.file.read()
    elif hasattr(file_obj, "read"):
        content = file_obj.read()
    elif hasattr(file_obj, "value"):
        content = file_obj.value

    if content is None:
        raise ValueError("Unable to read uploaded file content")
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raise TypeError(f"Unsupported uploaded content type: {type(content).__name__}")


def _raw_web_input():
    """Return unprocessed multipart form data when web.py exposes rawinput."""
    rawinput = getattr(getattr(web, "webapi", None), "rawinput", None)
    if not callable(rawinput):
        raise RuntimeError("web.py rawinput is not available")
    try:
        return rawinput(method="post")
    except TypeError:
        return rawinput()


def _ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class WebMessage(ChatMessage):
    def __init__(
            self,
            msg_id,
            content,
            ctype=ContextType.TEXT,
            from_user_id="User",
            to_user_id="Chatgpt",
            other_user_id="Chatgpt",
    ):
        self.msg_id = msg_id
        self.ctype = ctype
        self.content = content
        self.from_user_id = from_user_id
        self.to_user_id = to_user_id
        self.other_user_id = other_user_id


def _request_agent_id(source) -> str:
    value = getattr(source, "agent_id", None)
    if value is None:
        value = getattr(source, "agent", None)
    if value is None and isinstance(source, dict):
        value = source.get("agent_id") or source.get("agent")
    # web.py merges query string and form body, so a field present in both
    # arrives as a list. Collapse it to a single id rather than letting an
    # unhashable list reach registry lookups.
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value or None


def _scoped_agent_id(source) -> str:
    """The Agent a request is scoped to: its payload, or the URL's query string.

    Clients put ``agent_id`` in the query string and deliberately keep it out of
    a multipart body — web.py merges the two, and a field present in both
    arrives as a list that breaks handlers expecting a string (see the console's
    fetch wrapper and the desktop client's ``postFormData``). So a body read on
    its own — ``rawinput("post")``, or a JSON payload the client did not inject
    the field into — misses the Agent unless the query string is read too, and
    the request quietly answers as the default Agent instead of the selected one.
    """
    agent_id = _request_agent_id(source)
    if agent_id:
        return agent_id
    try:
        from urllib.parse import parse_qs

        query = parse_qs(web.ctx.env.get("QUERY_STRING") or "")
    except Exception:
        return None
    return _request_agent_id(query)


def _agent_badge(profile) -> dict:
    return {"id": profile.id, "name": profile.name, "avatar": profile.avatar or ""}


def _roster_from_members(host_agent_id: str, members) -> List[dict]:
    """Badge every reachable member of a conversation, host first.

    Same rule as ``agent.team_addressing.roster_from_members``, reserved
    "default" alias included: the browser and an IM group have to agree on who
    is reachable. Deduped on the resolved id, because an alias and the id it
    resolves to name one teammate.
    """
    from agent.multiagent import peer as peer_of
    from agent.registry import get_agent_registry

    if not members:
        return []
    registry = get_agent_registry()
    roster: List[dict] = []
    seen: set = set()
    for agent_id in [host_agent_id, *members]:
        try:
            badge = _agent_badge(registry.get_addressed(agent_id))
        except Exception:
            # A teammate hosted elsewhere: it has no local profile, but it is on
            # the team and must be listed. It carries no avatar of its own here.
            found = peer_of(agent_id)
            if found is None:
                continue
            badge = {"id": found.id, "name": found.name or found.id, "avatar": ""}
        if badge["id"] in seen:
            continue
        seen.add(badge["id"])
        roster.append(badge)
    return roster


def _session_roster(session_id: str, host_agent_id: str) -> List[dict]:
    """Everyone who can be addressed in this conversation, host included.

    Empty for a conversation nobody was invited into, which is every
    conversation until the user says otherwise.
    """
    from agent.workspace import session_prefs

    try:
        members = session_prefs.get_prefs(session_id, host_agent_id).get("members")
    except Exception as e:
        logger.debug(f"[WebChannel] roster lookup failed for {session_id}: {e}")
        return []
    return _roster_from_members(host_agent_id, members)


def _addressed_agent_id(text: str, roster: List[dict]) -> str:
    """The teammate this message names, or "" when it names nobody.

    Matching accepts the display name as well as the id, because the composer
    writes the name — nobody types ``@agent-17n3e8`` on purpose. Longer labels
    are tried first so that a name containing another name still resolves to
    the one actually written.

    Only a leading mention counts. Naming somebody mid-sentence is usually
    talking *about* them ("ask Ops to..."), not handing them the turn.
    """
    stripped = (text or "").lstrip()
    if not stripped.startswith("@"):
        return ""
    candidates = []
    for item in roster:
        for label in (item.get("name") or "", item.get("id") or ""):
            if label:
                candidates.append((label, item["id"]))
    for label, agent_id in sorted(candidates, key=lambda pair: -len(pair[0])):
        pattern = r"^@" + re.escape(label) + r"(?=[\s，,：:、]|$)"
        if re.match(pattern, stripped, re.IGNORECASE):
            return agent_id
    return ""


def _live_channel_manager():
    """Return the running ChannelManager, or None if the app is not up yet.

    app.py runs as ``python app.py``, so ``__main__`` is a *distinct* module
    object from a later ``import app``; reading ``_channel_mgr`` off
    ``sys.modules['__main__']`` therefore always yielded None and the console
    silently refused to start a newly configured channel. The manager is
    published through ``common.channel_registry`` instead (issue #3120).
    """
    try:
        return get_channel_manager()
    except Exception:
        return None


def _serve_allowed_roots() -> list:
    """Roots that /api/file and /preview may read from (symlinks resolved).

    Includes the configured serve root, the Agent workspace, and any project
    directory a session has opened. Project dirs may live outside the serve
    root (e.g. ``/tmp/foo``), so previewing files in an opened project would
    otherwise be denied.
    """
    serve_root = conf().get("web_file_serve_root", "~") or "~"
    roots = [
        os.path.realpath(os.path.expanduser(serve_root)),
        os.path.realpath(_get_workspace_root()),
    ]
    try:
        from agent.workspace import project_store
        for rec in project_store.list_recents():
            roots.append(os.path.realpath(rec["path"]))
    except Exception:
        pass
    return roots


def _is_path_allowed(real_path: str) -> bool:
    roots = _serve_allowed_roots()
    if os.sep in roots:
        return True
    for root in roots:
        try:
            if os.path.commonpath([real_path, root]) == root:
                return True
        except ValueError:
            continue
    return False
