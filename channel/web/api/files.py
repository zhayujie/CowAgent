"""Everything that moves bytes: uploads, downloads, preview, voice.

Attachments on the way in, workspace files and uploads on the way out, the
sandboxed preview iframe, and the two voice routes. The preview and file
routes are the ones a path traversal would hurt, so both gate on
_is_path_allowed.
"""

import base64
import datetime
import hashlib
import hmac
import json
import mimetypes
import os
import random
import re
import subprocess
import sys

import web

# ReplyType was never actually in scope here: web_channel.py reached for it
# through "from bridge.context import *", which does not export it, so a TTS
# reply raised NameError instead of being checked.
from bridge.reply import ReplyType
from channel.web.core._common import (
    _can_reveal_in_file_manager,
    _is_path_allowed,
    _get_preview_secret,
    _get_query_token,
    _get_upload_dir,
    _is_within_directory,
    _raw_web_input,
    _request_agent_id,
    _require_auth,
    _scoped_agent_id,
)
from channel.web.core.channel import WebChannel
from common.log import logger
from common.utils import constant_time_equals


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

# Types a browser runs scripts in when the file is opened directly. Agents
# write files from untrusted input, and such a page would otherwise run as the
# console's origin.
_ACTIVE_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml"}
_PAGE_SANDBOX = "sandbox allow-scripts allow-popups allow-forms allow-modals"


def _sandbox_active_content(content_type: str) -> None:
    """Give script-capable files an opaque origin; non-HTML ones get no scripts at all.

    A `?token=` stays readable from `location` even inside the sandbox, so a
    page opened with one gets no scripts either.
    """
    ct = content_type.split(";")[0].strip().lower()
    if ct not in _ACTIVE_TYPES and not ct.endswith("+xml"):
        return
    scripts = ct == "text/html" and not _get_query_token()
    web.header('X-Content-Type-Options', 'nosniff')
    web.header('Content-Security-Policy', _PAGE_SANDBOX if scripts else "sandbox")


def _file_body(path: str) -> bytes:
    """The file, or the one byte range the request asks for.

    Media players seek, and on phones even start some MP4s, with Range
    requests; without 206 answers a video can only be played straight
    through. Multi-range requests are rare enough to get the whole file.
    """
    size = os.path.getsize(path)
    web.header('Accept-Ranges', 'bytes')
    env = web.ctx.get('env') or {}
    m = _RANGE_RE.match((env.get('HTTP_RANGE') or '').strip())
    if not m or not (m.group(1) or m.group(2)):
        with open(path, 'rb') as f:
            return f.read()
    first, last = m.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        start, end = max(size - int(last), 0), size - 1
    if start >= size or start > end:
        web.ctx.status = '416 Range Not Satisfiable'
        web.header('Content-Range', f'bytes */{size}')
        return b''
    web.ctx.status = '206 Partial Content'
    web.header('Content-Range', f'bytes {start}-{end}/{size}')
    web.header('Content-Length', str(end - start + 1))
    with open(path, 'rb') as f:
        f.seek(start)
        return f.read(end - start + 1)


def _decode_dir_token(token: str) -> str:
    """Verify and decode a /preview directory token. Raises ValueError if invalid."""
    body, _, sig = (token or "").partition(".")
    if not body or not sig:
        raise ValueError("Malformed preview token")
    padding = "=" * (-len(body) % 4)
    try:
        real = base64.urlsafe_b64decode(body + padding).decode("utf-8")
    except Exception:
        raise ValueError("Malformed preview token")
    expected = hmac.new(_get_preview_secret(), real.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    if not constant_time_equals(sig, expected):
        raise ValueError("Bad preview token signature")
    return real


class UploadHandler:
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        return WebChannel().upload_file()


class VoiceAsrHandler:
    """Receive a mic recording, persist it under uploads/ and run ASR.
    Returns {status, text, audio_url} so the UI can render a playback bubble."""
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')

        saved_path = None
        try:
            params = _raw_web_input()
            agent_id = _scoped_agent_id(params)
            file_obj = params.get("file")
            if file_obj is None:
                return json.dumps({"status": "error", "message": "no audio file"})

            filename = getattr(file_obj, "filename", "") or "recording.webm"
            ext = os.path.splitext(filename)[1].lower() or ".webm"
            if ext not in (".webm", ".ogg", ".opus", ".mp4", ".m4a", ".mp3", ".wav"):
                ext = ".webm"

            upload_dir = _get_upload_dir(agent_id)
            os.makedirs(upload_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            saved_name = f"voice_input_{ts}_{random.randint(0, 9999)}{ext}"
            saved_path = os.path.join(upload_dir, saved_name)
            with open(saved_path, "wb") as f:
                f.write(file_obj.file.read() if hasattr(file_obj, "file") else file_obj.value)

            suffix = f"?agent_id={agent_id}" if agent_id else ""
            audio_url = f"/uploads/{saved_name}{suffix}"

            from bridge.bridge import Bridge
            reply = Bridge().fetch_voice_to_text(saved_path)
            if reply is None:
                return json.dumps({
                    "status": "error",
                    "message": "ASR returned no reply",
                    "audio_url": audio_url,
                })

            from bridge.reply import ReplyType
            if reply.type == ReplyType.TEXT:
                return json.dumps({
                    "status": "success",
                    "text": reply.content or "",
                    "audio_url": audio_url,
                })
            return json.dumps({
                "status": "error",
                "message": reply.content or "ASR failed",
                "audio_url": audio_url,
            })
        except Exception as e:
            logger.exception(f"[VoiceAsrHandler] failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class VoiceTtsHandler:
    """On-demand TTS for the in-chat "read aloud" button. Returns the
    audio URL and (when session_id is given) persists it onto the message."""
    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            data = json.loads(web.data() or b"{}")
            text = (data.get("text") or "").strip()
            session_id = (data.get("session_id") or "").strip()
            message_seq = data.get("message_seq")
            agent_id = data.get("agent_id")
            if not text:
                return json.dumps({"status": "error", "message": "empty text"})
            # `@singleton` makes WebChannel a factory function — go via instance.
            channel = WebChannel()
            if not channel._tts_provider_ready():
                return json.dumps({"status": "error", "message": "tts not configured"})

            target_store = None
            target_snapshot = None
            # Capture identity before synthesis: seq can be reused after a
            # deletion, and a message can change while audio is generated.
            if (session_id and isinstance(message_seq, int)
                    and not isinstance(message_seq, bool) and message_seq >= 0):
                try:
                    from agent.memory import get_conversation_store
                    from agent.registry import get_agent_registry
                    profile = get_agent_registry().get(agent_id)
                    target_store = get_conversation_store(profile.workspace)
                    target_snapshot = target_store.get_assistant_message_snapshot(session_id, message_seq)
                except Exception as e:
                    logger.debug(f"[VoiceTtsHandler] snapshot skipped: {e}")

            from bridge.bridge import Bridge
            reply = Bridge().fetch_text_to_voice(text)
            if reply is None or reply.type != ReplyType.VOICE or not reply.content:
                msg = getattr(reply, "content", "") or "tts failed"
                return json.dumps({"status": "error", "message": str(msg)})

            url = channel._publish_tts_audio(reply.content, agent_id)
            if not url:
                return json.dumps({"status": "error", "message": "publish failed"})

            # Ambiguous old clients and changed/deleted targets still receive
            # playback, without putting old audio onto another message.
            if target_store is not None and target_snapshot is not None:
                try:
                    target_store.attach_extras_to_assistant(
                        session_id, message_seq, {"audio": {"url": url, "kind": "tts"}}, target_snapshot,
                    )
                except Exception as e:
                    logger.debug(f"[VoiceTtsHandler] persist skipped: {e}")

            return json.dumps({"status": "success", "audio_url": url})
        except Exception as e:
            logger.exception(f"[VoiceTtsHandler] failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class UploadsHandler:
    def GET(self, file_name):
        _require_auth()
        try:
            params = web.input(agent_id='')
            upload_dir = _get_upload_dir(_request_agent_id(params))
            full_path = os.path.realpath(os.path.join(upload_dir, file_name))
            if not _is_within_directory(os.path.realpath(upload_dir), full_path):
                raise web.notfound()
            if not os.path.isfile(full_path):
                raise web.notfound()
            content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
            web.header('Content-Type', content_type)
            web.header('Cache-Control', 'public, max-age=86400')
            _sandbox_active_content(content_type)
            return _file_body(full_path)
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error(f"[WebChannel] Error serving upload: {e}")
            raise web.notfound()


class FileServeHandler:
    def GET(self):
        _require_auth()
        try:
            params = web.input(path="")
            file_path = params.path
            if not file_path or not os.path.isabs(file_path):
                raise web.notfound()
            # Resolve symlinks and confine access to the allowed root dirs,
            # so this endpoint can't be abused to read arbitrary files (e.g. /etc/passwd, ~/.ssh).
            # Defaults to the user home dir plus the agent workspace; set web_file_serve_root="/"
            # to allow the whole filesystem.
            file_path = os.path.realpath(file_path)
            if not _is_path_allowed(file_path):
                raise web.notfound()
            if not os.path.isfile(file_path):
                raise web.notfound()
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            file_name = os.path.basename(file_path)
            from urllib.parse import quote
            web.header('Content-Type', content_type)
            web.header('Content-Disposition', f"inline; filename*=UTF-8''{quote(file_name)}")
            # Workspace outputs can be regenerated at the same path, including
            # twice within an artifact URL's timestamp second. Revalidate the
            # current bytes instead of hiding an update behind an hour of cache.
            web.header('Cache-Control', 'no-cache')
            _sandbox_active_content(content_type)
            return _file_body(file_path)
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error(f"[WebChannel] Error serving file: {e}")
            raise web.notfound()


class FileRevealHandler:
    """POST /api/file/reveal {path}: show a file in the system file manager.

    Local-only (see _can_reveal_in_file_manager), and confined to the same
    roots /api/file serves from.
    """

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not _can_reveal_in_file_manager():
                return json.dumps({"status": "error", "message": "Only available on this machine"})
            data = json.loads(web.data() or b"{}")
            path = str(data.get("path") or "")
            if not path or not os.path.isabs(path):
                return json.dumps({"status": "error", "message": "path must be absolute"})
            path = os.path.realpath(path)
            if not _is_path_allowed(path) or not os.path.exists(path):
                return json.dumps({"status": "error", "message": "File not found"})
            _reveal_path(path)
            return json.dumps({"status": "success"})
        except Exception as e:
            logger.error(f"[WebChannel] Reveal in file manager failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


def _reveal_path(path: str) -> None:
    """Open the file manager on ``path``, selecting it where the OS can."""
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path], **quiet)
    elif sys.platform == "win32":
        # explorer wants the quotes inside its own /select, argument, which a
        # list argv would wrap the wrong way. Windows paths can't contain '"'.
        subprocess.Popen(f'explorer /select,"{path}"', **quiet)
    else:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.Popen(["xdg-open", target], start_new_session=True, **quiet)


# Injected into previewed HTML so the iframe's scrollbars match the app chrome
# instead of falling back to the platform default (wide, opaque track).
# Placed at the top of <head> so a page that styles its own scrollbars still wins.
_PREVIEW_SCROLLBAR_CSS = (
    "<style>"
    "html{scrollbar-width:thin;scrollbar-color:rgba(128,128,128,.45) transparent}"
    "::-webkit-scrollbar{width:8px;height:8px}"
    "::-webkit-scrollbar-track{background:transparent}"
    "::-webkit-scrollbar-corner{background:transparent}"
    "::-webkit-scrollbar-thumb{background:rgba(128,128,128,.45);border-radius:4px;"
    "border:2px solid transparent;background-clip:padding-box}"
    "::-webkit-scrollbar-thumb:hover{background:rgba(128,128,128,.7);"
    "background-clip:padding-box}"
    "</style>"
)

# Injected ahead of the page's own scripts, so a framed page scrolls only
# itself. A native scrollIntoView() or focus() inside an iframe also scrolls
# every scrollable ancestor of the frame in the host page: a page that
# brings "today" into view on load would drag the artifacts list, or the
# chat, along with it. Here both scroll the frame's own containers and
# viewport, and nothing above it. Opened as a tab, the page keeps the natives.
_PREVIEW_SCROLL_GUARD_JS = """<script>(function(){
if(window.top===window)return;
var E=Element.prototype,root=function(){return document.scrollingElement||document.documentElement;};
function delta(start,size,viewStart,viewSize,mode){
if(mode==='start')return start-viewStart;
if(mode==='end')return start+size-viewStart-viewSize;
if(mode==='center')return start+size/2-viewStart-viewSize/2;
if(start<viewStart)return start-viewStart;
if(start+size>viewStart+viewSize)return Math.min(start-viewStart,start+size-viewStart-viewSize);
return 0;}
function scrollable(n){var s=getComputedStyle(n);return /auto|scroll|overlay/.test(s.overflowX+s.overflowY)&&(n.scrollHeight>n.clientHeight||n.scrollWidth>n.clientWidth);}
E.scrollIntoView=function(arg){
var o=arg===false?{block:'end'}:(arg&&typeof arg==='object'?arg:{block:'start'});
var block=o.block||'start',inline=o.inline||'nearest',behavior=o.behavior||'auto',top=root();
for(var n=this.parentElement;n;n=n.parentElement){
var isRoot=n===top;if(!isRoot&&!scrollable(n))continue;
var r=this.getBoundingClientRect(),v=isRoot?{top:0,left:0}:n.getBoundingClientRect();
var vt=v.top+(isRoot?0:n.clientTop),vl=v.left+(isRoot?0:n.clientLeft);
var dy=delta(r.top,r.height,vt,isRoot?innerHeight:n.clientHeight,block);
var dx=delta(r.left,r.width,vl,isRoot?innerWidth:n.clientWidth,inline);
if(dx||dy)(isRoot?window:n).scrollBy({top:dy,left:dx,behavior:behavior});
if(isRoot)break;}};
var focus=HTMLElement.prototype.focus;
HTMLElement.prototype.focus=function(o){
var keep=o&&o.preventScroll;focus.call(this,Object.assign({},o,{preventScroll:true}));
if(!keep&&this.isConnected)this.scrollIntoView({block:'nearest'});};
})();</script>"""

_HEAD_OPEN_RE = re.compile(rb"<head\b[^>]*>", re.IGNORECASE)
_HTML_OPEN_RE = re.compile(rb"<html\b[^>]*>", re.IGNORECASE)


def _inject_preview_chrome(raw: bytes) -> bytes:
    """Insert the scrollbar stylesheet and the scroll guard into a previewed HTML document."""
    chrome = (_PREVIEW_SCROLLBAR_CSS + _PREVIEW_SCROLL_GUARD_JS).encode("utf-8")
    for pattern in (_HEAD_OPEN_RE, _HTML_OPEN_RE):
        m = pattern.search(raw)
        if m:
            return raw[: m.end()] + chrome + raw[m.end():]
    return chrome + raw


class PreviewHandler:
    """
    Directory-mounted file server for the preview panel: /preview/<token>/<relpath>

    Unlike /api/file (single file, query param) this mounts the file's directory,
    so relative assets inside a generated HTML page resolve normally. The token is
    HMAC-signed, which is what authorizes the request - the sandboxed iframe can't
    send the auth cookie.
    """

    def GET(self, path_info):
        try:
            token, _, rel_path = (path_info or "").partition("/")
            if not token or not rel_path:
                raise web.notfound()

            from urllib.parse import unquote
            rel_path = unquote(rel_path)

            try:
                base_dir = _decode_dir_token(token)
            except ValueError:
                raise web.notfound()

            full_path = os.path.realpath(os.path.join(base_dir, rel_path))
            base_real = os.path.realpath(base_dir)
            # Confine to the mounted directory, then to the globally allowed roots.
            if os.path.commonpath([full_path, base_real]) != base_real:
                raise web.notfound()
            if not _is_path_allowed(full_path) or not os.path.isfile(full_path):
                raise web.notfound()

            content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
            web.header('Content-Type', content_type)
            web.header('Cache-Control', 'no-cache')
            web.header('X-Content-Type-Options', 'nosniff')
            is_html = content_type.startswith("text/html")
            if is_html:
                # Agent-generated pages are untrusted. The CSP sandbox forces an
                # opaque origin even when the page is opened as a top-level tab,
                # so it can't read the console's localStorage auth token; the
                # panel's iframe already applies the same flags.
                #
                # No frame-ancestors here: the desktop renderer is loaded from
                # file:// (or the Vite dev server), so 'self' would block its
                # preview iframe outright. The sandbox is what carries the
                # security guarantee; framing alone reveals nothing extra.
                web.header('Content-Security-Policy', _PAGE_SANDBOX)
                with open(full_path, 'rb') as f:
                    return _inject_preview_chrome(f.read())
            _sandbox_active_content(content_type)
            return _file_body(full_path)
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error(f"[WebChannel] Error serving preview: {e}")
            raise web.notfound()
