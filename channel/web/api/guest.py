"""Guest share pages: the public side under /share/<token>, and the owner's side.

Two credential families that never mix:

- Visitor endpoints (``/share/<share_token>/...``) authenticate with a visitor
  token in the ``X-Guest-Token`` header. They never read the console cookie or
  bearer token, and no console endpoint accepts a visitor token: it is signed
  with a different key over a different payload, so ``_check_auth`` cannot
  verify it.
- Owner endpoints (``/api/guest-shares...``, used by the console's Share
  view) sit behind ``_require_auth`` like the rest of the console. Confirming a
  widened profile is only possible here.

Every visitor endpoint answers 404 while the feature is off, while the
console has no password, or for a token that names no confirmed profile, so
a probe learns nothing about which profiles exist.
"""

import json
import mimetypes
import os
import re
import tempfile
from urllib.parse import parse_qs, quote

import web

from agent.guest import branding
from agent.guest import share as share_mod
from agent.guest import store
from agent.guest.access import login_limiter
from agent.guest.paths import GuestPathError
from agent.guest.profile import (
    DATA_DIR,
    delete_profile,
    ensure_guests_readme,
    is_valid_slug,
    list_slugs,
    load_profile,
    new_slug,
)
from agent.guest.runtime import GuestError, available_skills, get_service, reference_suggestions
from channel.web.core import template
from channel.web.core._common import (
    _first_value,
    _multipart_lists,
    _read_uploaded_file_bytes_limited,
    _require_auth,
)
from common import i18n
from common.log import logger

TOKEN_HEADER = "HTTP_X_GUEST_TOKEN"
# Raster images are the only files shown inline. Anything else - HTML and SVG
# above all - is forced to download: it was written by a visitor's Agent and
# would otherwise run script on the console's origin.
_INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_SAFE_NAME_RE = re.compile(r"[^\w.\- ()\u4e00-\u9fff]+")


def _json(data, status: str = None):
    web.header("Content-Type", "application/json; charset=utf-8")
    web.header("Cache-Control", "no-store")
    if status:
        web.ctx.status = status
    return json.dumps(data, ensure_ascii=False)


def _fail(code: int, message: str, reason: str = ""):
    status = {
        400: "400 Bad Request", 401: "401 Unauthorized", 403: "403 Forbidden",
        404: "404 Not Found", 409: "409 Conflict", 413: "413 Payload Too Large",
        429: "429 Too Many Requests",
    }.get(code, f"{code} Error")
    raise web.HTTPError(
        status,
        {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
        json.dumps({"status": "error", "message": message, "reason": reason}, ensure_ascii=False),
    )


def _client_ip() -> str:
    env = getattr(web.ctx, "env", {}) or {}
    addr = (env.get("REMOTE_ADDR") or "").strip()
    # Forwarding headers are only believed from a proxy on this machine;
    # anyone else could set them to dodge the per-client limits.
    if addr in ("::1", "::ffff:127.0.0.1") or addr.startswith("127."):
        forwarded = (env.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
        real = (env.get("HTTP_X_REAL_IP") or "").strip()
        return forwarded or real or addr
    return addr or "unknown"


def _body() -> dict:
    try:
        data = json.loads(web.data() or b"{}")
    except (ValueError, TypeError):
        _fail(400, "Invalid JSON body")
    if not isinstance(data, dict):
        _fail(400, "Invalid JSON body")
    return data


def _load_share(share_token: str, require_active: bool = True):
    if not share_mod.feature_status()["serving"]:
        _fail(404, "Not found")
    state = share_mod.resolve_by_token(share_token)
    if state is None or state.effective is None:
        _fail(404, "Not found")
    if require_active and not state.active:
        _fail(403, "This page is not available right now.", state.status)
    return state


def _visitor(state) -> str:
    token = (web.ctx.env.get(TOKEN_HEADER) or "").strip()
    visitor_id = store.verify_token(token, state.slug, state.session_ttl())
    if not visitor_id:
        _fail(401, "Session expired, please reload the page.", "session_invalid")
    return visitor_id


def _query(name: str) -> str:
    # Read from the query string only: web.input() would consume a multipart
    # upload body before the handler gets to it.
    values = parse_qs((web.ctx.query or "").lstrip("?")).get(name) or [""]
    return values[0]


def _owned_session(state, visitor_id: str, session_id: str = None) -> str:
    """The conversation a request names, if it is this visitor's and still
    theirs to use."""
    session_id = session_id if session_id is not None else _query("sid")
    if not store.owns_session(visitor_id, session_id):
        _fail(404, "Conversation not found.", "session_not_found")
    if store.is_deleted(state.slug, session_id):
        _fail(404, "Conversation not found.", "session_not_found")
    return session_id


def _asr_available() -> bool:
    """Whether the owner has a speech recognition provider that can answer."""
    from config import conf

    try:
        from channel.web.api.models import ModelsHandler

        cap = ModelsHandler._asr_capability(conf())
    except Exception:
        return False
    provider = cap.get("current_provider") or cap.get("suggested_provider") or ""
    if not provider:
        return False
    if provider.startswith("custom"):
        return True
    from channel.web.core.providers import PROVIDER_MODELS, is_real_key

    key_field = (PROVIDER_MODELS.get(provider) or {}).get("api_key_field")
    return not key_field or is_real_key(conf().get(key_field, ""))


def _frame_ancestors(state) -> str:
    origins = ((state.effective or {}).get("access") or {}).get("allowed_origins") or []
    return " ".join(["'self'"] + origins)


def _page_brand(state) -> dict:
    """The page's look, rendered into it so nothing flashes the default first."""
    if state is None:
        return {"color": "", "palette": None, "on": "", "logo": "", "footer_text": "", "footer_url": ""}
    cfg = (state.effective or {}).get("branding") or {}
    color = cfg.get("color") or ""
    version = branding.logo_version(state.profile.path)
    return {
        "color": color,
        "palette": branding.palette(color) if color else None,
        "on": branding.on_color(color) if color else "",
        "logo": f"/share/{state.share_token}/api/logo?v={version}" if version else "",
        "footer_text": cfg.get("footer_text") or "",
        "footer_url": cfg.get("footer_url") or "",
    }


def _send_image(data: bytes, mime: str):
    web.header("Content-Type", mime)
    web.header("X-Content-Type-Options", "nosniff")
    web.header("Content-Security-Policy", "sandbox; default-src 'none'")
    # Versioned URLs change with the logo; the bare one (embed.js) must not
    # keep an old logo for long.
    web.header("Cache-Control", "private, max-age=86400" if _query("v") else "private, max-age=300")
    return data


# --- visitor side ------------------------------------------------------------


class GuestPageHandler:
    def GET(self, share_token):
        try:
            state = _load_share(share_token, require_active=False)
        except web.HTTPError:
            # Still a 404, but a page that says the link does not work rather
            # than raw JSON; it names nothing about which links exist.
            state = None
            web.ctx.status = "404 Not Found"
        web.header("Content-Type", "text/html; charset=utf-8")
        web.header("Cache-Control", "no-store")
        # The share token is in the URL; keep it out of Referer headers sent
        # to whatever the visitor clicks next.
        web.header("Referrer-Policy", "no-referrer")
        web.header("X-Content-Type-Options", "nosniff")
        ancestors = _frame_ancestors(state) if state is not None else "'self'"
        web.header("Content-Security-Policy", f"frame-ancestors {ancestors}")
        brand = _page_brand(state)
        html = template.render("templates/guest/page.html")
        return (html.replace("{{COW_DEFAULT_LANG}}", i18n.get_language())
                .replace("{{GUEST_BRAND}}", json.dumps(brand).replace("<", "\\u003c"))
                .replace("{{GUEST_LOGO}}", brand["logo"] or "/assets/logo.jpg")
                .replace("{{GUEST_ICON}}", brand["logo"] or "/assets/favicon.ico"))


class GuestLogoHandler:
    """The page's own logo. Open to anyone holding the link, as the
    password screen shows it before the visitor is in."""

    def GET(self, share_token):
        state = _load_share(share_token, require_active=False)
        logo = branding.read_logo(state.profile.path)
        if logo is None:
            _fail(404, "Not found")
        return _send_image(*logo)


class GuestInfoHandler:
    def GET(self, share_token):
        state = _load_share(share_token, require_active=False)
        cfg = state.effective
        return _json({
            "status": "success",
            "available": state.active,
            "reason": "" if state.active else state.status,
            "name": cfg.get("name") or "",
            "welcome": cfg.get("welcome") or "",
            "suggested_questions": cfg.get("suggested_questions") or [],
            "password_required": bool((cfg.get("access") or {}).get("password_required")),
            "upload": "write" in (cfg.get("tools") or []) or "read" in (cfg.get("tools") or []),
            "max_upload_mb": int((cfg.get("limits") or {}).get("max_upload_mb") or 20),
            "voice": _asr_available(),
        })


class GuestSessionHandler:
    """Admit a visitor, or renew the token the page kept so an active
    visitor keeps their conversations past the token's lifetime."""

    def POST(self, share_token):
        state = _load_share(share_token)
        service = get_service()
        client = _client_ip()
        if not service.allow_ip(f"session:{client}", 30):
            _fail(429, "Too many requests, please wait a moment.", "rate_limited")
        data = _body()
        previous = str(data.get("token") or "")
        if previous:
            visitor_id = store.verify_token(previous, state.slug, state.session_ttl())
            if visitor_id:
                return _json({"status": "success", "token": store.issue_token(state.slug, visitor_id),
                              "resumed": True})

        if (state.effective.get("access") or {}).get("password_required"):
            wait = login_limiter.locked_for(state.slug, client)
            if wait:
                _fail(429, f"Too many attempts. Try again in {wait} seconds.", "locked")
            password = str(data.get("password") or "")
            if not password:
                _fail(401, "Password required.", "password_required")
            if not store.verify_password(password, (state.entry or {}).get("password_hash") or ""):
                login_limiter.failed(state.slug, client)
                logger.warning(f"[GuestShare] Wrong password for {state.slug} from {client}")
                _fail(401, "Wrong password.", "password_wrong")
            login_limiter.succeeded(state.slug, client)

        token = store.issue_token(state.slug, store.new_visitor_id())
        return _json({"status": "success", "token": token, "resumed": False})


class GuestConversationsHandler:
    """The visitor's own conversations: list them, or open a new one. A new
    conversation is only an id until its first message is stored."""

    def GET(self, share_token):
        state = _load_share(share_token)
        visitor_id = _visitor(state)
        return _json({"status": "success", "sessions": store.visitor_sessions(state.slug, visitor_id)})

    def POST(self, share_token):
        state = _load_share(share_token)
        visitor_id = _visitor(state)
        if not get_service().allow_ip(f"conv:{_client_ip()}", 30):
            _fail(429, "Too many requests, please wait a moment.", "rate_limited")
        return _json({"status": "success", "session_id": store.new_session_id(visitor_id)})


class GuestConversationHandler:
    def DELETE(self, share_token, session_id):
        state = _load_share(share_token)
        session_id = _owned_session(state, _visitor(state), session_id)
        get_service().delete_session(state, session_id)
        return _json({"status": "success"})


class GuestClearHandler:
    def POST(self, share_token, session_id):
        state = _load_share(share_token)
        session_id = _owned_session(state, _visitor(state), session_id)
        try:
            get_service().clear_context(state, session_id)
        except GuestError as e:
            _fail(e.code, e.message, e.reason)
        return _json({"status": "success"})


class GuestHistoryHandler:
    def GET(self, share_token):
        state = _load_share(share_token)
        session_id = _owned_session(state, _visitor(state))
        return _json(dict(get_service().history(state, session_id), status="success"))


class GuestMessageHandler:
    def POST(self, share_token):
        state = _load_share(share_token)
        visitor_id = _visitor(state)
        session_id = _owned_session(state, visitor_id)
        service = get_service()
        if not service.allow_ip(f"msg:{_client_ip()}", 60):
            _fail(429, "Too many requests, please wait a moment.", "rate_limited")
        data = _body()
        attachments = data.get("attachments") or []
        if not isinstance(attachments, list):
            attachments = []
        try:
            request_id = service.start(
                state, visitor_id, session_id, str(data.get("text") or ""),
                [str(a) for a in attachments if isinstance(a, str)],
            )
        except GuestError as e:
            _fail(e.code, e.message, e.reason)
        return _json({"status": "success", "request_id": request_id})


class GuestStreamHandler:
    def GET(self, share_token):
        state = _load_share(share_token)
        session_id = _owned_session(state, _visitor(state))
        params = web.input(request_id="", after="0")
        run = get_service().get_run(params.request_id, state.slug, session_id)
        if run is None:
            _fail(404, "Unknown request.", "unknown_request")
        try:
            after = int(params.after or 0)
        except ValueError:
            after = 0
        web.header("Content-Type", "text/event-stream; charset=utf-8")
        web.header("Cache-Control", "no-cache")
        web.header("X-Accel-Buffering", "no")
        return get_service().stream(run, after)


class GuestCancelHandler:
    def POST(self, share_token):
        state = _load_share(share_token)
        session_id = _owned_session(state, _visitor(state))
        return _json({"status": "success", "cancelled": get_service().cancel(state.slug, session_id)})


class GuestUploadHandler:
    MAX_PARTS = 4

    def POST(self, share_token):
        state = _load_share(share_token)
        session_id = _owned_session(state, _visitor(state))
        service = get_service()
        if not service.allow_ip(f"upload:{_client_ip()}", 20):
            _fail(429, "Too many uploads, please wait a moment.", "rate_limited")
        limits = state.effective.get("limits") or {}
        max_bytes = int(limits.get("max_upload_mb") or 20) * 1024 * 1024
        try:
            declared = int(web.ctx.env.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        if declared > max_bytes + 64 * 1024:
            _fail(413, "File is too large.", "too_large")
        guard = service.guard_for(state, session_id)
        work_limit = int(limits.get("max_work_mb") or 200) * 1024 * 1024
        if guard.work_usage_bytes() + declared > work_limit:
            _fail(413, "This conversation's storage is full.", "storage_full")
        try:
            params = _multipart_lists(self.MAX_PARTS)
            file_obj = _first_value(params, "file")
            if file_obj is None:
                _fail(400, "No file uploaded.")
            content = _read_uploaded_file_bytes_limited(file_obj, max_bytes)
        except web.HTTPError:
            raise
        except ValueError:
            _fail(413, "File is too large.", "too_large")
        except Exception as e:
            logger.warning(f"[GuestShare] Upload failed: {e}")
            _fail(400, "Upload failed.")
        raw_name = getattr(file_obj, "filename", "") or getattr(file_obj, "raw_filename", "") or "file"
        name = _SAFE_NAME_RE.sub("_", os.path.basename(str(raw_name).replace("\\", "/"))).strip(" .") or "file"
        name = name[-120:]
        uploads = os.path.join(guard.work_dir, "uploads")
        os.makedirs(uploads, exist_ok=True)
        stem, ext = os.path.splitext(name)
        target, n = os.path.join(uploads, name), 1
        while os.path.exists(target):
            target = os.path.join(uploads, f"{stem}_{n}{ext}")
            n += 1
        with open(target, "wb") as f:
            f.write(content)
        vpath = guard.virtual_of(target)
        is_image = (mimetypes.guess_type(target)[0] or "").startswith("image/")
        return _json({
            "status": "success", "path": vpath, "name": os.path.basename(target), "size": len(content),
            "file_type": "image" if is_image else "file",
            "url": service.file_url(state.share_token, state.slug, session_id, vpath),
        })


class GuestVoiceHandler:
    """Speech to text for the visitor's mic button, through the owner's ASR
    provider. The recording is transcribed and thrown away."""

    MAX_BYTES = 10 * 1024 * 1024
    MAX_PARTS = 4

    def POST(self, share_token):
        state = _load_share(share_token)
        _visitor(state)
        if not _asr_available():
            _fail(404, "Voice input is not available.", "voice_unavailable")
        if not get_service().allow_ip(f"asr:{_client_ip()}", 20):
            _fail(429, "Too many requests, please wait a moment.", "rate_limited")
        try:
            params = _multipart_lists(self.MAX_PARTS)
            file_obj = _first_value(params, "file")
            if file_obj is None:
                _fail(400, "No audio uploaded.")
            content = _read_uploaded_file_bytes_limited(file_obj, self.MAX_BYTES)
        except web.HTTPError:
            raise
        except ValueError:
            _fail(413, "Recording is too long.", "too_large")
        except Exception as e:
            logger.warning(f"[GuestShare] Voice upload failed: {e}")
            _fail(400, "Upload failed.")
        raw_name = getattr(file_obj, "filename", "") or "recording.webm"
        ext = os.path.splitext(str(raw_name))[1].lower()
        if ext not in (".webm", ".ogg", ".opus", ".mp4", ".m4a", ".mp3", ".wav"):
            ext = ".webm"
        fd, path = tempfile.mkstemp(prefix="guest_voice_", suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            from bridge.bridge import Bridge
            from bridge.reply import ReplyType

            reply = Bridge().fetch_voice_to_text(path)
        except Exception as e:
            logger.warning(f"[GuestShare] ASR failed for {state.slug}: {e}")
            reply = None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if reply is None or reply.type != ReplyType.TEXT or not (reply.content or "").strip():
            _fail(502, "Could not recognise the recording.", "voice_failed")
        return _json({"status": "success", "text": reply.content.strip()})


class GuestFileHandler:
    """Serve a file the visitor's Agent sent. Authorized by a signed link, so
    it works as a plain <a href> or <img src>."""

    def GET(self, share_token):
        state = _load_share(share_token)
        params = web.input(sid="", path="", exp="0", sig="")
        try:
            expires = int(params.exp)
        except ValueError:
            _fail(404, "Not found")
        if not params.sid.isalnum() or not store.verify_file(state.slug, params.sid, params.path, expires, params.sig):
            _fail(404, "Not found")
        guard = get_service().guard_for(state, params.sid)
        try:
            real = guard.resolve(params.path)
        except GuestPathError:
            _fail(404, "Not found")
        if not os.path.isfile(real):
            _fail(404, "Not found")
        mime = mimetypes.guess_type(real)[0] or "application/octet-stream"
        name = os.path.basename(real)
        inline = mime in _INLINE_TYPES
        web.header("Content-Type", mime if inline else "application/octet-stream")
        web.header("Content-Disposition",
                   f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(name)}")
        web.header("X-Content-Type-Options", "nosniff")
        web.header("Content-Security-Policy", "sandbox; default-src 'none'")
        web.header("Cache-Control", "private, max-age=3600")
        web.header("Referrer-Policy", "no-referrer")
        with open(real, "rb") as f:
            return f.read()


# --- owner side --------------------------------------------------------------


def _owner_state(slug: str):
    if not is_valid_slug(slug):
        _fail(404, "Not found")
    state = share_mod.resolve(slug)
    if state is None:
        _fail(404, "Not found")
    return state


def _owner_view(state, detail: bool = False) -> dict:
    data = share_mod.describe(state)
    if detail:
        data["raw_config"] = state.profile.config
        data["guest_md"] = state.profile.guest_md
    return data


class GuestSharesHandler:
    def GET(self):
        _require_auth()
        feature = share_mod.feature_status()
        if feature["enabled"]:
            ensure_guests_readme()
        shares = []
        for slug in list_slugs():
            state = share_mod.resolve(slug)
            if state is not None:
                shares.append(_owner_view(state))
        try:
            from channel.web.api.sessions import _session_model_catalog

            models = _session_model_catalog()
        except Exception as e:
            logger.debug(f"[GuestShare] Model catalog unavailable: {e}")
            models = []
        return _json({
            "status": "success",
            "feature": feature,
            "shares": shares,
            "skills": available_skills(),
            "references": reference_suggestions(),
            "models": models,
        })

    def POST(self):
        _require_auth()
        data = _body()
        slug = str(data.get("slug") or "").strip() or new_slug()
        if slug == DATA_DIR:
            _fail(400, f"'{DATA_DIR}' is reserved, choose another id.")
        if not is_valid_slug(slug):
            _fail(400, "Profile id must be lowercase letters, digits, '-' or '_' (max 40).")
        if load_profile(slug) is not None:
            _fail(409, "A profile with this id already exists.")
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        guest_md = data.get("guest_md") if isinstance(data.get("guest_md"), str) else None
        ensure_guests_readme()
        state = share_mod.save_and_confirm(slug, config, guest_md)
        return _json({"status": "success", "share": _owner_view(state, detail=True)})

    def PUT(self):
        """Switch the feature itself on or off (``guest_share.enabled``)."""
        _require_auth()
        from channel.web.api.integrations import save_config_values
        from config import conf

        enabled = _body().get("enabled") is True
        section = dict(conf().get("guest_share") or {})
        section["enabled"] = enabled
        save_config_values({"guest_share": section})
        logger.info(f"[GuestShare] Feature {'enabled' if enabled else 'disabled'} from the console")
        return _json({"status": "success", "feature": share_mod.feature_status()})


class GuestShareHandler:
    def GET(self, slug):
        _require_auth()
        return _json({"status": "success", "share": _owner_view(_owner_state(slug), detail=True)})

    def PUT(self, slug):
        _require_auth()
        _owner_state(slug)
        data = _body()
        config = data.get("config")
        if not isinstance(config, dict):
            _fail(400, "config must be an object")
        guest_md = data.get("guest_md") if isinstance(data.get("guest_md"), str) else None
        state = share_mod.save_and_confirm(slug, config, guest_md)
        return _json({"status": "success", "share": _owner_view(state, detail=True)})

    def DELETE(self, slug):
        _require_auth()
        _owner_state(slug)
        get_service().forget_profile(slug)
        store.purge(slug)
        delete_profile(slug)
        return _json({"status": "success"})


class GuestShareActionHandler:
    def POST(self, slug, action):
        _require_auth()
        _owner_state(slug)
        service = get_service()
        if action == "confirm":
            share_mod.confirm_current(slug)
        elif action == "reset-link":
            store.reset_link(slug)
            service.forget_profile(slug)
        elif action == "revoke":
            store.revoke_sessions(slug)
            service.forget_profile(slug)
        elif action == "password":
            from config import conf

            password = str(_body().get("password") or "")
            if password and len(password) < 6:
                _fail(400, "Password must be at least 6 characters.")
            if password and password == str(conf().get("web_password") or ""):
                _fail(400, "Use a password different from the console password.", "console_password")
            store.set_password(slug, password)
            login_limiter.reset(slug)
            service.forget_profile(slug)
        elif action == "disable":
            store.update_entry(slug, disabled=True)
            service.forget_profile(slug)
        elif action == "enable":
            store.update_entry(slug, disabled=False)
        logger.info(f"[GuestShare] Owner action {action} on {slug}")
        return _json({"status": "success", "share": _owner_view(_owner_state(slug), detail=True)})


class GuestShareLogoHandler:
    MAX_PARTS = 4

    def GET(self, slug):
        _require_auth()
        logo = branding.read_logo(_owner_state(slug).profile.path)
        if logo is None:
            _fail(404, "Not found")
        return _send_image(*logo)

    def POST(self, slug):
        _require_auth()
        state = _owner_state(slug)
        try:
            declared = int(web.ctx.env.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        if declared > branding.MAX_LOGO_BYTES + 64 * 1024:
            _fail(413, "The image is larger than 2 MB.", "too_large")
        try:
            params = _multipart_lists(self.MAX_PARTS)
            file_obj = _first_value(params, "file")
            if file_obj is None:
                _fail(400, "No file uploaded.")
            content = _read_uploaded_file_bytes_limited(file_obj, branding.MAX_LOGO_BYTES)
        except web.HTTPError:
            raise
        except ValueError:
            _fail(413, "The image is larger than 2 MB.", "too_large")
        except Exception as e:
            logger.warning(f"[GuestShare] Logo upload failed: {e}")
            _fail(400, "Upload failed.")
        try:
            branding.save_logo(state.profile.path, content)
        except ValueError as e:
            if str(e) == "too_large":
                _fail(413, "The image is larger than 2 MB.", "too_large")
            _fail(400, "Use a PNG, JPG or WebP image.", "unsupported_image")
        return _json({"status": "success", "share": _owner_view(_owner_state(slug), detail=True)})

    def DELETE(self, slug):
        _require_auth()
        branding.remove_logo(_owner_state(slug).profile.path)
        return _json({"status": "success", "share": _owner_view(_owner_state(slug), detail=True)})


class GuestShareLogsHandler:
    def GET(self, slug):
        _require_auth()
        _owner_state(slug)
        return _json({"status": "success", "sessions": store.list_sessions(slug)})


class GuestShareLogHandler:
    def GET(self, slug, session_id):
        _require_auth()
        _owner_state(slug)
        return _json({"status": "success", "records": store.read_messages(slug, session_id, 2000)})


GUEST_URLS = (
    '/share/([A-Za-z0-9_-]{16,64})/?', 'GuestPageHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/info', 'GuestInfoHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/logo', 'GuestLogoHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/session', 'GuestSessionHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/sessions', 'GuestConversationsHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/sessions/([a-f0-9]{36})', 'GuestConversationHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/sessions/([a-f0-9]{36})/clear', 'GuestClearHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/voice', 'GuestVoiceHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/history', 'GuestHistoryHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/message', 'GuestMessageHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/stream', 'GuestStreamHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/cancel', 'GuestCancelHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/upload', 'GuestUploadHandler',
    '/share/([A-Za-z0-9_-]{16,64})/api/file', 'GuestFileHandler',
    '/api/guest-shares', 'GuestSharesHandler',
    '/api/guest-shares/([a-z0-9][a-z0-9_-]{0,39})', 'GuestShareHandler',
    '/api/guest-shares/([a-z0-9][a-z0-9_-]{0,39})/(confirm|reset-link|revoke|password|disable|enable)',
    'GuestShareActionHandler',
    '/api/guest-shares/([a-z0-9][a-z0-9_-]{0,39})/logo', 'GuestShareLogoHandler',
    '/api/guest-shares/([a-z0-9][a-z0-9_-]{0,39})/logs', 'GuestShareLogsHandler',
    '/api/guest-shares/([a-z0-9][a-z0-9_-]{0,39})/logs/([a-f0-9]{1,64})', 'GuestShareLogHandler',
)
