"""Signing in to the console, and the MCP OAuth callback.

The console's own password check plus the redirect target an MCP server
sends the user back to after authorising it.
"""

import html
import json

import web

from agent.guest.access import LoginLimiter
from channel.web.api.devices import issue_password_device
from channel.web.core import devices
from channel.web.core._common import (
    _check_auth,
    _client_ip,
    _current_device_token,
    _get_web_password,
    _is_password_enabled,
)
from common.log import logger
from common.utils import constant_time_equals

# Once the console listens beyond this machine, anyone on the network can try
# passwords; this caps the guessing per client and across all clients. Clients
# on this machine are counted apart, so guessing from the network cannot lock
# the owner out locally.
_login_limiter = LoginLimiter()


def _limiter_scope(client: str) -> str:
    local = client in ("::1", "::ffff:127.0.0.1", "localhost") or client.startswith("127.")
    return "console-local" if local else "console"


class McpOAuthCallbackHandler:
    """OAuth redirect target for MCP servers requiring authorization.

    The browser lands here after the user authorizes a remote MCP server.
    We exchange the authorization code for tokens and bring the server
    online. Unauthenticated by design: the OAuth `state` param is the
    single-use secret that binds this request to a pending authorization.
    """

    def GET(self):
        web.header('Content-Type', 'text/html; charset=utf-8')
        params = web.input(code="", state="", error="", error_description="")

        def _page(title: str, message: str) -> str:
            # This page is reachable without a session by design (the OAuth
            # `state` param is the secret), and `error` / `error_description`
            # come straight from the query string while `server_name` comes
            # from mcp.json — all attacker-controllable text rendered into the
            # console's origin. Escape both fields so a crafted callback URL
            # cannot run script here (e.g. same-origin fetches with the
            # victim's session cookie).
            title = html.escape(title)
            message = html.escape(message)
            return (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<title>{title}</title></head>"
                "<body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
                "max-width:520px;margin:64px auto;padding:0 20px;text-align:center;color:#1f2328'>"
                f"<h2>{title}</h2><p style='color:#57606a'>{message}</p></body></html>"
            )

        if params.error:
            logger.warning(f"[MCP-OAuth] callback error: {params.error} {params.error_description}")
            return _page("授权失败", f"{params.error}: {params.error_description or ''}")

        if not params.code or not params.state:
            return _page("参数缺失", "回调缺少 code 或 state 参数。")

        try:
            from agent.tools.mcp.mcp_oauth import pop_pending
            from agent.tools.mcp.mcp_client import notify_server_authorized
        except Exception as e:
            logger.warning(f"[MCP-OAuth] callback import failed: {e}")
            return _page("内部错误", "OAuth 模块不可用。")

        handler = pop_pending(params.state)
        if handler is None:
            return _page("会话已过期", "授权请求不存在或已过期，请重新触发授权。")

        try:
            ok = handler.finish_authorization(params.code)
        except Exception as e:
            logger.warning(f"[MCP-OAuth] token exchange crashed: {e}")
            ok = False

        if not ok:
            return _page("授权失败", "换取令牌失败，请重试。")

        notify_server_authorized(handler.server_name)
        logger.info(f"[MCP-OAuth] Server '{handler.server_name}' authorized via web callback")
        return _page(
            "授权成功",
            f"MCP 服务 “{handler.server_name}” 已授权，可以返回聊天继续使用了。",
        )


class AuthCheckHandler:
    def GET(self):
        web.header('Content-Type', 'application/json; charset=utf-8')
        if not _is_password_enabled():
            return json.dumps({"status": "success", "auth_required": False})
        if _check_auth():
            return json.dumps({"status": "success", "auth_required": True, "authenticated": True})
        return json.dumps({"status": "success", "auth_required": True, "authenticated": False})


class AuthLoginHandler:
    def POST(self):
        web.header('Content-Type', 'application/json; charset=utf-8')
        if not _is_password_enabled():
            return json.dumps({"status": "success"})
        try:
            data = json.loads(web.data())
        except Exception:
            return json.dumps({"status": "error", "message": "Invalid request"})
        client = _client_ip()
        scope = _limiter_scope(client)
        wait = _login_limiter.locked_for(scope, client)
        if wait:
            return json.dumps({"status": "error", "reason": "locked", "retry_after": wait,
                               "message": f"Too many attempts. Try again in {wait} seconds."})
        password = str(data.get("password", "") or "")
        expected = _get_web_password()
        if not constant_time_equals(password, expected):
            _login_limiter.failed(scope, client)
            logger.warning(f"[WebChannel] Invalid login attempt from {client}")
            return json.dumps({"status": "error", "reason": "wrong_password", "message": "Wrong password"})
        _login_limiter.succeeded(scope, client)
        token = issue_password_device(data.get("device"))
        # Also return the token in the body: the desktop client (file:// origin)
        # can't rely on the cookie and sends it back via an Authorization header.
        return json.dumps({"status": "success", "token": token})


class AuthLogoutHandler:
    def POST(self):
        web.header('Content-Type', 'application/json; charset=utf-8')
        # Signing out gives the device's token up for good.
        token = _current_device_token()
        web.setcookie("cow_auth_token", "", expires=-1, path="/")
        if devices.verify(token):
            device_id = devices.device_id_of(token)
            devices.remove(device_id)
            logger.info(f"[WebChannel] Device {device_id} signed out")
        return json.dumps({"status": "success"})
