"""Environment manager API. Authentication matches the original settings API."""

import json
from functools import wraps
from urllib.parse import parse_qs, urlsplit

import web

from channel.web.core._common import _require_auth
from channel.web.core.env_store import EnvStore, EnvStoreError


def _store():
    # EnvConfig is deliberately instantiated lazily. Imports never open .env.
    from agent.tools.env_config.env_config import EnvConfig
    from bridge.bridge import Bridge

    # Inspect the already-running bridge; do not initialise an Agent merely
    # because somebody opened settings.
    bridge = getattr(Bridge(), "_agent_bridge", None)
    return EnvStore(EnvConfig({"agent_bridge": bridge}))


def _same_origin(origin):
    from channel.web.api.integrations import public_url

    expected = [urlsplit(web.ctx.homedomain)]
    # TLS-terminating proxies leave WSGI's scheme as http. Reuse the existing
    # public URL setting instead of trusting arbitrary forwarding headers.
    external = public_url()
    if external:
        parsed = urlsplit(external)
        expected.append(parsed._replace(path="", query="", fragment=""))
    return origin != "null" and urlsplit(origin) in expected


def _endpoint(write=False):
    def decorate(method):
        @wraps(method)
        def wrapped(*args, **kwargs):
            web.header("Content-Type", "application/json; charset=utf-8")
            web.header("Cache-Control", "no-store")
            web.header("Pragma", "no-cache")
            web.header("X-Content-Type-Options", "nosniff")
            _require_auth()
            try:
                env = web.ctx.env
                origin = env.get("HTTP_ORIGIN")
                # Custom header + JSON forces a CORS preflight for foreign
                # origins. This API never grants CORS; Origin is checked too.
                if origin and not _same_origin(origin):
                    raise EnvStoreError("cross_origin", 403)
                if env.get("HTTP_SEC_FETCH_SITE") in ("cross-site", "same-site"):
                    raise EnvStoreError("cross_origin", 403)
                if write:
                    if env.get("HTTP_X_COW_ENV_REQUEST") != "1":
                        raise EnvStoreError("csrf", 403)
                    if env.get("CONTENT_TYPE", "").split(";")[0].strip().lower() != "application/json":
                        raise EnvStoreError("json_required", 415)
                    size = int(env.get("CONTENT_LENGTH") or 0)
                    if size < 0 or size > 65536:
                        raise EnvStoreError("request_too_large", 413)
                # web.input() merges JSON bodies in newer web.py releases.
                # Inspect only the URL, never interpret credentials as params.
                params = parse_qs(env.get("QUERY_STRING", ""), keep_blank_values=True)
                if set(params) - {"q", "agent_id", "token"}:
                    raise EnvStoreError("invalid_query")
                return json.dumps({"status": "success", **method(*args, **kwargs)}, ensure_ascii=False)
            except EnvStoreError as error:
                web.ctx.status = {400: "400 Bad Request", 403: "403 Forbidden", 404: "404 Not Found",
                                  409: "409 Conflict", 413: "413 Payload Too Large", 415: "415 Unsupported Media Type"}[error.status]
                return json.dumps({"status": "error", "code": error.code})
            except Exception:
                # Never stringify exceptions: codecs, dotenv and third-party
                # clients may embed submitted credentials in their messages.
                web.ctx.status = "503 Service Unavailable"
                return json.dumps({"status": "error", "code": "storage_unavailable"})
        return wrapped
    return decorate


def _body(allowed):
    raw = web.data()
    if len(raw) > 65536:
        raise EnvStoreError("request_too_large", 413)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise EnvStoreError("invalid_json") from None
    # The console's existing fetch wrapper injects agent_id into JSON. .env
    # remains process-wide; that field must never select a different file.
    if not isinstance(data, dict) or set(data) - (set(allowed) | {"agent_id"}):
        raise EnvStoreError("invalid_request")
    data.pop("agent_id", None)
    return data


class EnvVariablesHandler:
    @_endpoint()
    def GET(self):
        query = parse_qs(web.ctx.env.get("QUERY_STRING", "")).get("q", [""])[-1]
        if len(query) > 500:
            raise EnvStoreError("invalid_query")
        return _store().list(query)

    @_endpoint(write=True)
    def POST(self):
        data = _body({"key", "value"})
        return _store().mutate("create", data.pop("key", None), **data)


class EnvVariableHandler:
    @_endpoint()
    def GET(self, key):
        return {"variable": _store().get(key)}

    @_endpoint(write=True)
    def PUT(self, key):
        return _store().mutate("update", key, **_body({"value"}))

    @_endpoint(write=True)
    def DELETE(self, key):
        _body(set())
        return _store().mutate("delete", key)


class EnvSyncHandler:
    @_endpoint(write=True)
    def POST(self):
        _body(set())
        return _store().sync()
