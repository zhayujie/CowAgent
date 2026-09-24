"""
MCP (Model Context Protocol) client module.

Implements JSON-RPC 2.0 over stdio, SSE and Streamable HTTP transports
without any external MCP SDK dependency.
"""

import json
import os
import queue
import subprocess
import threading
import urllib.request
import urllib.error
from typing import Optional

from common.log import logger


# Aliases accepted for the Streamable HTTP transport type
_STREAMABLE_HTTP_ALIASES = {"streamable-http", "streamable_http", "streamablehttp", "http"}


# System env vars a stdio MCP subprocess legitimately needs to run
# (node/python/npx toolchains). Everything else is dropped by default so
# API keys living in the agent's own environment don't leak into servers.
_STDIO_ENV_PASSTHROUGH = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TZ", "TMPDIR", "NODE_PATH", "NVM_DIR", "PYTHONPATH", "PYTHONHOME",
    # Windows essentials
    "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA",
    "LOCALAPPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "PROGRAMDATA", "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH",
)
# Sensitive name patterns never forwarded, even under inherit_full_env.
_STDIO_ENV_SENSITIVE = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_PASSWD", "_CREDENTIAL")


# Optional callback invoked after an OAuth authorization completes, so the
# tool manager can bring the newly-authorized server online. Signature:
# reload_fn(server_name: str) -> None. Installed by the tool manager.
_reload_callback = None


def set_reload_callback(fn) -> None:
    """Register a callback fired after a server's OAuth flow succeeds."""
    global _reload_callback
    _reload_callback = fn


def notify_server_authorized(server_name: str) -> None:
    """Called by the web callback once tokens are stored for a server."""
    fn = _reload_callback
    if fn is None:
        logger.debug(f"[MCP:{server_name}] Authorized but no reload callback registered")
        return
    try:
        fn(server_name)
    except Exception as e:
        logger.warning(f"[MCP:{server_name}] reload callback failed: {e}")


def stdio_command_allowed(command: str, server_name: str = "") -> bool:
    """Return whether *command* may be used to spawn a stdio MCP server.

    Fail-closed: an empty or missing ``mcp_stdio_command_allowlist`` denies
    every command. Set the list in config.json, for example
    ``["npx", "node", "python", "python3", "uvx"]``.
    """
    label = server_name or "?"
    try:
        from config import conf
        allowlist = conf().get("mcp_stdio_command_allowlist")
    except Exception:
        allowlist = None
    if not allowlist:
        logger.warning(
            f"[MCP:{label}] mcp_stdio_command_allowlist is empty; "
            f"refusing to start stdio command {command!r}. Set it in "
            f'config.json (e.g. ["npx", "node", "python", "python3", "uvx"]).'
        )
        return False
    base = os.path.basename(str(command)).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    if base in {str(c).lower() for c in allowlist}:
        return True
    logger.warning(
        f"[MCP:{label}] command '{command}' not in "
        f"mcp_stdio_command_allowlist, refusing to start"
    )
    return False


def _oauth_redirect_uri() -> str:
    """Build the OAuth redirect URI served by the web console callback.

    Priority: explicit mcp_oauth_redirect_base config, otherwise the local
    web console address (127.0.0.1:<web_port>). Both point at the shared
    /mcp/oauth/callback route.
    """
    try:
        from config import conf
        base = (conf().get("mcp_oauth_redirect_base") or "").strip().rstrip("/")
        if not base:
            port = int(os.environ.get("COW_WEB_PORT") or conf().get("web_port", 9899))
            base = f"http://127.0.0.1:{port}"
    except Exception:
        base = "http://127.0.0.1:9899"
    return f"{base}/mcp/oauth/callback"


class McpClient:
    """Single MCP Server client supporting stdio, SSE and Streamable HTTP transports."""

    def __init__(self, config: dict):
        """
        config examples:
          stdio:           {"name": "filesystem", "type": "stdio", "command": "npx", "args": [...]}
          SSE:             {"name": "my-api",    "type": "sse",   "url": "http://localhost:8000/sse"}
          streamable-http: {"name": "pubmed",    "type": "streamable-http", "url": "https://x/mcp"}
        """
        self.config = config
        self.name: str = config.get("name", "unknown")
        raw_transport: str = config.get("type", "stdio")
        # Per-server timeout for tool calls (default 120s, suitable for data queries)
        self._timeout: int = int(config.get("timeout", 120))
        # Normalize streamable-http aliases to a single internal key
        self.transport: str = (
            "streamable-http"
            if raw_transport.lower() in _STREAMABLE_HTTP_ALIASES
            else raw_transport
        )

        # stdio state
        self._proc: Optional[subprocess.Popen] = None
        self._read_queue: queue.Queue = queue.Queue()

        # SSE state
        self._sse_url: Optional[str] = None
        self._post_url: Optional[str] = None  # endpoint for sending messages (resolved from SSE)

        # Streamable HTTP state
        self._http_url: Optional[str] = None
        self._http_headers: dict = {}  # extra headers from user config (e.g. Authorization)
        self._http_session_id: Optional[str] = None  # Mcp-Session-Id assigned by the server

        # OAuth state (streamable-http only). Lazily created when the server
        # responds with 401 and the user has not supplied a static token.
        self._oauth = None  # OAuthHandler instance
        # Set to True once a 401 could not be satisfied and the user must
        # complete the browser authorization. Callers can surface this state.
        self.needs_auth: bool = False

        # Shared state
        self._next_id = 1
        self._id_lock = threading.Lock()
        # _call_lock serializes all requests on the single stdio pipe.
        # SSE and streamable-http use independent HTTP requests, so they
        # do not acquire this lock (see _send_request).
        self._call_lock = threading.Lock()
        # _http_lock protects _http_session_id initialization across
        # concurrent streamable-http requests.
        self._http_lock = threading.Lock()
        # Blocks new requests while an expired session is being replaced.
        # An RLock lets the recovery handshake use the normal HTTP path.
        self._http_reinit_lock = threading.RLock()
        self._initialized = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Connect and perform the MCP handshake. Returns True on success."""
        try:
            if self.transport == "stdio":
                return self._init_stdio()
            elif self.transport == "sse":
                return self._init_sse()
            elif self.transport == "streamable-http":
                return self._init_streamable_http()
            else:
                logger.warning(f"[MCP:{self.name}] Unknown transport type: {self.transport!r}")
                return False
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] Initialization failed: {e}")
            return False

    def list_tools(self) -> list:
        """Return the tool list from this server.

        Each item is a dict: {"name": str, "description": str, "inputSchema": dict}
        """
        try:
            resp = self._send_request("tools/list", {})
            tools = resp.get("result", {}).get("tools", [])
            return [
                {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                }
                for t in tools
            ]
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] list_tools failed: {e}")
            return []

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool and return the result as a string."""
        try:
            resp = self._send_request("tools/call", {"name": name, "arguments": arguments})
            content = resp.get("result", {}).get("content", [])
            parts = [item.get("text", "") for item in content if item.get("type") == "text"]
            return "\n".join(parts)
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] call_tool({name}) failed: {e}")
            return f"Error: {e}"

    def shutdown(self):
        """Close the connection / terminate the child process."""
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            logger.debug(f"[MCP:{self.name}] stdio process terminated")

        # Best-effort streamable-http session termination
        if self.transport == "streamable-http" and self._http_session_id and self._http_url:
            try:
                req = urllib.request.Request(
                    self._http_url,
                    method="DELETE",
                    headers={"Mcp-Session-Id": self._http_session_id, **self._http_headers},
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
            except Exception:
                pass
            self._http_session_id = None

        self._initialized = False

    # ------------------------------------------------------------------
    # stdio transport
    # ------------------------------------------------------------------

    def _init_stdio(self) -> bool:
        command = self.config.get("command")
        if not command:
            logger.warning(f"[MCP:{self.name}] stdio config missing 'command'")
            return False

        if not stdio_command_allowed(command, self.name):
            return False

        args = self.config.get("args", [])
        env = self._build_stdio_env(self.config.get("env", None))

        self._proc = subprocess.Popen(
            [command] + list(args),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        logger.debug(f"[MCP:{self.name}] stdio process started (pid={self._proc.pid})")

        threading.Thread(
            target=self._drain_stderr, daemon=True, name=f"mcp-stderr-{self.name}"
        ).start()
        threading.Thread(
            target=self._drain_stdout, daemon=True, name=f"mcp-stdout-{self.name}"
        ).start()

        return self._handshake()

    def _command_allowed(self, command: str) -> bool:
        """Check the executable against ``mcp_stdio_command_allowlist``."""
        return stdio_command_allowed(command, self.name)

    def _build_stdio_env(self, extra_env) -> dict:
        """Build the environment for a stdio MCP subprocess.

        By default only safe system vars plus the user's explicit ``env``
        block are passed through, so API keys in the agent's own environment
        are not leaked to the subprocess. Set the per-server config
        ``inherit_full_env: true`` to restore full inheritance (obviously
        sensitive names are still stripped).
        """
        extra_env = extra_env or {}
        if self.config.get("inherit_full_env"):
            env = {
                k: v for k, v in os.environ.items()
                if not any(p in k.upper() for p in _STDIO_ENV_SENSITIVE)
            }
        else:
            env = {k: os.environ[k] for k in _STDIO_ENV_PASSTHROUGH if k in os.environ}
        # User-declared env is explicit authorization, always applied last.
        env.update({str(k): str(v) for k, v in extra_env.items()})
        return env

    def _url_allowed(self, url: str) -> bool:
        """SSRF guard for remote (SSE / streamable-http) MCP endpoints.

        Delegates to the shared ``validate_url_safe`` helper, which is a no-op
        unless ``web_security_ssrf_protection`` is enabled, so local/LAN MCP
        servers keep working by default.
        """
        try:
            from agent.tools.utils.url_safety import validate_url_safe
            validate_url_safe(url)
            return True
        except ValueError as e:
            logger.warning(f"[MCP:{self.name}] url blocked: {e}")
            return False

    def _drain_stderr(self):
        for line in self._proc.stderr:
            line = line.strip()
            if line:
                logger.warning(f"[MCP:{self.name}] stderr: {line}")

    def _drain_stdout(self):
        """Background thread: read lines from stdout and put them into the queue."""
        try:
            for line in self._proc.stdout:
                self._read_queue.put(line)
        except Exception:
            pass
        finally:
            try:
                self._read_queue.put("")
            except Exception:
                pass

    def _readline_with_timeout(self, timeout: Optional[int] = None) -> str:
        """Read one line from stdio stdout with a hard timeout (cross-platform).

        Uses the per-server timeout from mcp.json config when no explicit
        timeout is provided.
        """
        effective = timeout if timeout is not None else self._timeout
        try:
            line = self._read_queue.get(timeout=effective)
        except queue.Empty:
            raise TimeoutError(f"[MCP:{self.name}] stdio read timed out after {effective}s")
        if not line:
            raise IOError(f"[MCP:{self.name}] stdio process closed unexpectedly")
        return line

    def _stdio_send(self, message: dict) -> dict:
        """Send a JSON-RPC message over stdio and read the response."""
        raw = json.dumps(message) + "\n"
        self._proc.stdin.write(raw)
        self._proc.stdin.flush()

        expected_id = message.get("id")
        while True:
            line = self._readline_with_timeout()
            if not line:
                raise IOError(f"[MCP:{self.name}] stdio process closed unexpectedly")
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" not in data:
                logger.debug(f"[MCP:{self.name}] notification skipped: {data.get('method', '?')}")
                continue
            # Verify response id matches request id to avoid consuming a stale
            # response left over from a previously failed/timed-out request.
            if data.get("id") != expected_id:
                logger.warning(
                    f"[MCP:{self.name}] Stale response id={data.get('id')} "
                    f"(expected {expected_id}), skipping"
                )
                continue
            return data

    # ------------------------------------------------------------------
    # SSE transport
    # ------------------------------------------------------------------

    def _init_sse(self) -> bool:
        url = self.config.get("url")
        if not url:
            logger.warning(f"[MCP:{self.name}] SSE config missing 'url'")
            return False

        if not self._url_allowed(url):
            return False

        self._sse_url = url

        # Read the first SSE event to discover the POST endpoint
        try:
            self._post_url = self._sse_discover_endpoint()
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] SSE endpoint discovery failed: {e}")
            return False

        return self._handshake()

    def _sse_discover_endpoint(self) -> str:
        """Open SSE stream and read the 'endpoint' event to learn the POST URL."""
        req = urllib.request.Request(
            self._sse_url,
            headers={"Accept": "text/event-stream"},
        )
        endpoint = None
        with urllib.request.urlopen(req, timeout=10) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n\r")
                if line.startswith("data:"):
                    data = line[len("data:"):].strip()
                    # Some servers send JSON with a "uri" or plain path
                    if data.startswith("{"):
                        parsed = json.loads(data)
                        endpoint = parsed.get("uri") or parsed.get("url") or parsed.get("endpoint")
                    elif data.startswith("http"):
                        # Plain absolute URL
                        endpoint = data
                    else:
                        # Relative path: resolve against SSE base
                        from urllib.parse import urljoin
                        endpoint = urljoin(self._sse_url, data)
                    break
        if not endpoint:
            raise ValueError(f"[MCP:{self.name}] No endpoint event received from SSE stream")
        # Re-validate the server-supplied POST endpoint to block redirects
        # into internal addresses (SSRF guard; no-op when protection is off).
        from agent.tools.utils.url_safety import validate_url_safe
        validate_url_safe(endpoint)
        return endpoint

    def _sse_send(self, message: dict) -> dict:
        """POST a JSON-RPC message to the server and return the response."""
        body = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(
            self._post_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)

    # ------------------------------------------------------------------
    # Streamable HTTP transport (MCP spec 2025-03-26)
    # ------------------------------------------------------------------

    def _init_streamable_http(self) -> bool:
        url = self.config.get("url")
        if not url:
            logger.warning(f"[MCP:{self.name}] streamable-http config missing 'url'")
            return False

        if not self._url_allowed(url):
            return False

        self._http_url = url
        # Allow user-provided headers (e.g. {"Authorization": "Bearer xxx"})
        extra_headers = self.config.get("headers") or {}
        if isinstance(extra_headers, dict):
            self._http_headers = {str(k): str(v) for k, v in extra_headers.items()}

        # Restore any previously stored OAuth credentials for this server so a
        # restart reuses the token instead of forcing re-authorization.
        self._maybe_load_oauth()

        return self._handshake()

    # ------------------------------------------------------------------
    # OAuth helpers (streamable-http only)
    # ------------------------------------------------------------------

    def _has_static_auth(self) -> bool:
        """True when the user supplied their own Authorization header."""
        return any(k.lower() == "authorization" for k in self._http_headers)

    def _maybe_load_oauth(self) -> None:
        """Attach an OAuthHandler when stored credentials exist for this server."""
        if self._has_static_auth():
            return
        try:
            from agent.tools.mcp.mcp_oauth import OAuthHandler, load_server_record
        except Exception:
            return
        rec = load_server_record(self.name)
        # Only create a handler when we have something to reuse; otherwise it
        # is created lazily on the first 401.
        if rec.get("access_token") or rec.get("client_id"):
            self._oauth = OAuthHandler(
                server_name=self.name,
                resource_url=self._http_url,
                redirect_uri=_oauth_redirect_uri(),
                scope=self.config.get("scope", ""),
            )

    def _current_bearer(self) -> Optional[str]:
        """Return a valid access token, refreshing if needed."""
        if self._oauth is None:
            return None
        return self._oauth.get_valid_access_token()

    def _begin_oauth(self, www_authenticate: str = "") -> None:
        """Kick off the OAuth flow after a 401: discover, register, prompt user."""
        if self._has_static_auth():
            return
        try:
            from agent.tools.mcp.mcp_oauth import OAuthHandler
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] OAuth module unavailable: {e}")
            return

        if self._oauth is None:
            self._oauth = OAuthHandler(
                server_name=self.name,
                resource_url=self._http_url,
                redirect_uri=_oauth_redirect_uri(),
                scope=self.config.get("scope", ""),
            )

        if not self._oauth.ensure_registered(www_authenticate):
            logger.warning(
                f"[MCP:{self.name}] OAuth discovery/registration failed; "
                f"cannot authorize automatically"
            )
            return

        auth_url = self._oauth.build_authorization_url()
        if not auth_url:
            logger.warning(f"[MCP:{self.name}] Failed to build authorization URL")
            return

        self.needs_auth = True
        logger.warning(
            f"[MCP:{self.name}] ⚠️  Authorization required. Open this URL in a "
            f"browser to authorize, then this server will come online automatically:\n"
            f"    {auth_url}"
        )
        # On a machine with a local browser (desktop/dev), open it directly.
        if os.environ.get("COW_DESKTOP") == "1" or not os.environ.get("COW_HEADLESS"):
            try:
                import webbrowser
                webbrowser.open(auth_url)
            except Exception:
                pass

    def _streamable_http_send(self, message: dict) -> dict:
        """POST a JSON-RPC request and return the response (JSON or SSE-wrapped)."""
        return self._streamable_http_post(message, expect_response=True)

    def _handle_401(
        self,
        err,
        message: dict,
        expect_response: bool,
        retried: bool,
        session_retried: bool = False,
    ) -> dict:
        """Handle a 401: refresh the token and retry once, else begin OAuth."""
        www_auth = ""
        try:
            www_auth = err.headers.get("WWW-Authenticate", "") or ""
        except Exception:
            pass
        try:
            err.read()
        except Exception:
            pass

        # First try a silent refresh with the stored refresh token.
        if not retried and self._oauth is not None and self._oauth.refresh():
            logger.info(f"[MCP:{self.name}] Token refreshed after 401, retrying")
            return self._streamable_http_post(
                message,
                expect_response,
                _retried=True,
                _session_retried=session_retried,
            )

        # No usable token — start (or restart) the interactive OAuth flow.
        self._begin_oauth(www_auth)
        raise IOError(
            f"[MCP:{self.name}] streamable-http HTTP 401: authorization required "
            f"(complete the OAuth flow to enable this server)"
        )

    def _streamable_http_post(
        self,
        message: dict,
        expect_response: bool,
        _retried: bool = False,
        _session_retried: bool = False,
    ) -> dict:
        """
        POST a JSON-RPC message over Streamable HTTP.

        Per the spec, the response Content-Type can be either:
          - application/json   -> single JSON-RPC response in body
          - text/event-stream  -> SSE stream; we read until we get a matching response
        """
        body = json.dumps(message).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # Do not start a request between invalidating an expired session and
        # completing the replacement handshake.
        with self._http_reinit_lock:
            with self._http_lock:
                sid = self._http_session_id
        if sid:
            headers["Mcp-Session-Id"] = sid
        headers.update(self._http_headers)
        # Inject OAuth bearer token when we have one (unless the user set a
        # static Authorization header, which takes precedence).
        if not self._has_static_auth():
            token = self._current_bearer()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(
            self._http_url,
            data=body,
            method="POST",
            headers=headers,
        )

        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            # 401 is the spec-compliant "needs authorization" signal.
            if e.code == 401 and not self._has_static_auth():
                return self._handle_401(
                    e,
                    message,
                    expect_response,
                    _retried,
                    _session_retried,
                )
            if (
                e.code == 404
                and sid
                and not _session_retried
                and message.get("method") != "initialize"
            ):
                try:
                    e.read()
                except Exception:
                    pass
                self._replace_expired_http_session(sid)
                return self._streamable_http_post(
                    message,
                    expect_response,
                    _retried=_retried,
                    _session_retried=True,
                )
            # Surface the server-provided error body for easier debugging
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            raise IOError(
                f"[MCP:{self.name}] streamable-http HTTP {e.code}: {detail[:200]}"
            )

        with resp:
            # Capture session id assigned by the server (if any)
            session_id = resp.headers.get("Mcp-Session-Id")
            # Double-checked lock: only the first response sets the
            # session id, preventing concurrent initializers from
            # overwriting each other.
            if (
                session_id
                and (message.get("method") == "initialize" or sid is None)
                and not self._http_session_id
            ):
                with self._http_lock:
                    if not self._http_session_id:
                        self._http_session_id = session_id

            status = resp.status if hasattr(resp, "status") else resp.getcode()

            # Notifications: server may reply with 202 Accepted and no body
            if not expect_response or status == 202:
                try:
                    resp.read()
                except Exception:
                    pass
                return {}

            content_type = (resp.headers.get("Content-Type") or "").lower()
            expected_id = message.get("id")

            if "text/event-stream" in content_type:
                return self._read_sse_response(resp, expected_id)

            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)

    def _replace_expired_http_session(self, expired_session_id: str) -> None:
        """Replace an expired Streamable HTTP session once across callers."""
        with self._http_reinit_lock:
            with self._http_lock:
                if self._http_session_id != expired_session_id:
                    if not self._initialized:
                        raise IOError(
                            f"[MCP:{self.name}] failed to reinitialize expired HTTP session"
                        )
                    return
                self._http_session_id = None

            if not self._handshake():
                raise IOError(
                    f"[MCP:{self.name}] failed to reinitialize expired HTTP session"
                )

    def _read_sse_response(self, resp, expected_id) -> dict:
        """Read an SSE stream and return the first JSON-RPC response with matching id."""
        data_buf: list = []
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\n\r")
            if line == "":
                # End of an SSE event, attempt to parse accumulated data
                if data_buf:
                    payload = "\n".join(data_buf)
                    data_buf = []
                    try:
                        msg = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # Skip notifications / mismatched ids
                    if "id" not in msg:
                        continue
                    if expected_id is None or msg.get("id") == expected_id:
                        return msg
                continue
            if line.startswith(":"):
                continue  # SSE comment / keepalive
            if line.startswith("data:"):
                data_buf.append(line[len("data:"):].lstrip())
            # Ignore 'event:' / 'id:' lines; we only care about JSON-RPC payloads

        raise IOError(f"[MCP:{self.name}] streamable-http SSE stream closed before response")

    # ------------------------------------------------------------------
    # Common JSON-RPC helpers
    # ------------------------------------------------------------------

    def _next_request_id(self) -> int:
        with self._id_lock:
            rid = self._next_id
            self._next_id += 1
        return rid

    def _build_request(self, method: str, params: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params,
        }

    def _build_notification(self, method: str, params: dict) -> dict:
        return {"jsonrpc": "2.0", "method": method, "params": params}

    def _send_request(self, method: str, params: dict) -> dict:
        """Send a request and return the full response dict."""
        if not self._initialized and method != "initialize":
            raise RuntimeError(f"[MCP:{self.name}] Client not initialized")

        message = self._build_request(method, params)

        # stdio transport uses a single pipe and must be serialized.
        # SSE and streamable-http use independent HTTP requests and
        # can safely run concurrently across sessions.
        if self.transport == "stdio":
            with self._call_lock:
                return self._stdio_send(message)
        elif self.transport == "sse":
            return self._sse_send(message)
        elif self.transport == "streamable-http":
            return self._streamable_http_send(message)
        else:
            raise ValueError(f"[MCP:{self.name}] Unsupported transport: {self.transport}")

    def _send_notification(self, method: str, params: dict):
        """Fire-and-forget notification (no response expected)."""
        notification = self._build_notification(method, params)
        raw = json.dumps(notification) + "\n"

        if self.transport == "stdio":
            self._proc.stdin.write(raw)
            self._proc.stdin.flush()
        elif self.transport == "sse":
            body = raw.encode("utf-8")
            req = urllib.request.Request(
                self._post_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except Exception:
                pass  # notifications are fire-and-forget
        elif self.transport == "streamable-http":
            try:
                self._streamable_http_post(notification, expect_response=False)
            except Exception:
                pass  # notifications are fire-and-forget

    def _handshake(self) -> bool:
        """Perform the MCP initialize / notifications/initialized handshake."""
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "CowAgent", "version": "1.0"},
        }
        # Temporarily mark as initialized so _send_request doesn't block
        self._initialized = True
        try:
            resp = self._send_request("initialize", init_params)
        except Exception as e:
            self._initialized = False
            logger.warning(f"[MCP:{self.name}] Handshake initialize failed: {e}")
            return False

        if "error" in resp:
            self._initialized = False
            logger.warning(f"[MCP:{self.name}] Handshake error: {resp['error']}")
            return False

        self._send_notification("notifications/initialized", {})
        logger.debug(f"[MCP:{self.name}] Handshake complete")
        return True


class McpClientRegistry:
    """Global singleton managing the lifecycle of all MCP Server clients."""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._clients: dict[str, McpClient] = {}
                obj._registry_lock = threading.Lock()
                # Process-wide pool of booted clients keyed by their *source*
                # config, so several Agents that resolve to the same shared
                # mcp.json reuse one subprocess instead of each forking its own.
                # Keyed by (mcp_json_path, server_name, config_signature): an
                # Agent with its own mcp.json, or a different command/env, gets a
                # distinct key and stays isolated.
                obj._shared_pool: dict[tuple, McpClient] = {}
                obj._shared_pool_lock = threading.Lock()
                # Per-key boot locks so that when several Agents' loader threads
                # miss the pool for the same server at once, only one forks the
                # subprocess and the rest wait and reuse it (instead of racing
                # and each booting a duplicate).
                obj._boot_locks: dict[tuple, threading.Lock] = {}
                cls._instance = obj
        return cls._instance

    @staticmethod
    def shared_key(mcp_json_path: str, server_name: str, cfg: dict) -> tuple:
        import json as _json
        try:
            sig = _json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            sig = repr(cfg)
        return (mcp_json_path or "", server_name, sig)

    def get_shared_client(self, key: tuple):
        """Return a live pooled client for this exact config, or None. A client
        whose subprocess has died is dropped so the caller boots a fresh one."""
        with self._shared_pool_lock:
            client = self._shared_pool.get(key)
        if client is None:
            return None
        if not self._shared_client_alive(client):
            with self._shared_pool_lock:
                # Only evict the exact object we found dead; a concurrent reload
                # may already have put a fresh one under the same key.
                if self._shared_pool.get(key) is client:
                    self._shared_pool.pop(key, None)
            return None
        return client

    def put_shared_client(self, key: tuple, client: "McpClient") -> None:
        with self._shared_pool_lock:
            self._shared_pool[key] = client

    def _boot_lock_for(self, key: tuple) -> "threading.Lock":
        with self._shared_pool_lock:
            lock = self._boot_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._boot_locks[key] = lock
            return lock

    def get_or_boot_shared(self, key: tuple, factory):
        """Return a pooled client for ``key``, booting it via ``factory`` if
        absent. Serialized per key so concurrent loader threads don't each fork
        a duplicate; distinct keys still boot in parallel.

        Returns (client, reused). ``client`` is None when ``factory`` failed to
        produce a usable client (e.g. init failed / needs auth); ``reused`` is
        True when an already-booted subprocess was handed back.
        """
        client = self.get_shared_client(key)
        if client is not None:
            return client, True
        with self._boot_lock_for(key):
            # Re-check: another thread may have booted it while we waited.
            client = self.get_shared_client(key)
            if client is not None:
                return client, True
            client = factory()
            if client is None:
                return None, False
            self.put_shared_client(key, client)
            return client, False

    @staticmethod
    def _shared_client_alive(client: "McpClient") -> bool:
        """Best-effort liveness: a stdio client whose child process has exited
        must not be reused. Unknown/remote transports are assumed alive."""
        proc = getattr(client, "_proc", None)
        if proc is not None and hasattr(proc, "poll"):
            try:
                return proc.poll() is None
            except Exception:
                return False
        return True

    def start_all(self, configs: list) -> None:
        """Initialize McpClient for each config entry; skip failures with a warning."""
        if not configs:
            return

        for cfg in configs:
            name = cfg.get("name", "<unnamed>")
            client = McpClient(cfg)
            ok = client.initialize()
            if ok:
                with self._registry_lock:
                    self._clients[name] = client
                logger.info(f"[MCP] Server '{name}' initialized successfully")
            else:
                logger.warning(f"[MCP] Server '{name}' failed to initialize — skipping")

    def get(self, server_name: str) -> Optional[McpClient]:
        """Return the initialized client for server_name, or None."""
        with self._registry_lock:
            return self._clients.get(server_name)

    def all_clients(self) -> dict:
        """Return a copy of the {name: McpClient} mapping."""
        with self._registry_lock:
            return dict(self._clients)

    def shutdown_all(self) -> None:
        """Shut down all managed clients."""
        with self._registry_lock:
            clients = list(self._clients.values())
            self._clients.clear()

        for client in clients:
            try:
                client.shutdown()
            except Exception as e:
                logger.warning(f"[MCP] Error shutting down '{client.name}': {e}")

        logger.info("[MCP] All servers shut down")
