"""
MCP (Model Context Protocol) client module.

Implements JSON-RPC 2.0 over stdio and SSE transports without any external
MCP SDK dependency.
"""

import json
import os
import select
import subprocess
import threading
import urllib.request
import urllib.error
from typing import Optional

from common.log import logger


class McpClient:
    """Single MCP Server client supporting stdio and SSE transports."""

    def __init__(self, config: dict):
        """
        config examples:
          stdio: {"name": "filesystem", "type": "stdio", "command": "npx", "args": [...]}
          SSE:   {"name": "my-api",    "type": "sse",   "url": "http://localhost:8000/sse"}
        """
        self.config = config
        self.name: str = config.get("name", "unknown")
        self.transport: str = config.get("type", "stdio")

        # stdio state
        self._proc: Optional[subprocess.Popen] = None

        # SSE state
        self._sse_url: Optional[str] = None
        self._post_url: Optional[str] = None  # endpoint for sending messages (resolved from SSE)

        # Shared state
        self._next_id = 1
        self._id_lock = threading.Lock()
        self._call_lock = threading.Lock()
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
        self._initialized = False

    # ------------------------------------------------------------------
    # stdio transport
    # ------------------------------------------------------------------

    def _init_stdio(self) -> bool:
        command = self.config.get("command")
        if not command:
            logger.warning(f"[MCP:{self.name}] stdio config missing 'command'")
            return False

        args = self.config.get("args", [])
        extra_env = self.config.get("env", None)
        env = {**os.environ, **extra_env} if extra_env else None

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

        return self._handshake()

    def _drain_stderr(self):
        for line in self._proc.stderr:
            line = line.strip()
            if line:
                logger.debug(f"[MCP:{self.name}] stderr: {line}")

    def _readline_with_timeout(self, timeout: int = 30) -> str:
        """Read one line from stdio stdout with a hard timeout."""
        ready, _, _ = select.select([self._proc.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError(f"[MCP:{self.name}] stdio read timed out after {timeout}s")
        return self._proc.stdout.readline()

    def _stdio_send(self, message: dict) -> dict:
        """Send a JSON-RPC message over stdio and read the response."""
        raw = json.dumps(message) + "\n"
        self._proc.stdin.write(raw)
        self._proc.stdin.flush()

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
            return data

    # ------------------------------------------------------------------
    # SSE transport
    # ------------------------------------------------------------------

    def _init_sse(self) -> bool:
        url = self.config.get("url")
        if not url:
            logger.warning(f"[MCP:{self.name}] SSE config missing 'url'")
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n\r")
                if line.startswith("data:"):
                    data = line[len("data:"):].strip()
                    # Some servers send JSON with a "uri" or plain path
                    if data.startswith("{"):
                        parsed = json.loads(data)
                        return parsed.get("uri") or parsed.get("url") or parsed.get("endpoint")
                    # Plain relative or absolute URL
                    if data.startswith("http"):
                        return data
                    # Relative path: resolve against SSE base
                    from urllib.parse import urljoin
                    return urljoin(self._sse_url, data)
        raise ValueError(f"[MCP:{self.name}] No endpoint event received from SSE stream")

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

        with self._call_lock:
            if self.transport == "stdio":
                return self._stdio_send(message)
            elif self.transport == "sse":
                return self._sse_send(message)
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
                cls._instance = obj
        return cls._instance

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
