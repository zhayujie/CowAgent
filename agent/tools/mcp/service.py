"""MCP server configuration used by the web and desktop consoles.

The file of record is workspace mcp.json in Claude/Cursor mcpServers form.
ToolManager already hot-reloads that file; this module is the validate / read /
write / dry-run layer sitting in front of it.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional
from urllib.parse import urlparse

from common.log import logger


_STREAMABLE_HTTP_ALIASES = {
    "streamable-http",
    "streamable_http",
    "streamablehttp",
    "http",
}
_VALID_TYPES = {"stdio", "sse", "streamable-http"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KNOWN_FIELDS = {
    "name",
    "type",
    "command",
    "args",
    "env",
    "url",
    "headers",
    "scope",
    "tool_name_prefix",
    "disabled",
    "timeout",
}
# UI-only; never persisted.
_EPHEMERAL_FIELDS = {"status", "tools", "error", "ok", "needs_auth"}


class McpConfigError(ValueError):
    """Raised when an MCP server entry is missing required fields."""


def mcp_is_disabled(cfg: dict) -> bool:
    val = cfg.get("disabled", False)
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def normalize_transport(raw: Any, *, has_url: bool = False) -> str:
    text = (raw or "").strip().lower() if isinstance(raw, str) else ""
    if text in _STREAMABLE_HTTP_ALIASES:
        return "streamable-http"
    if text in _VALID_TYPES:
        return text
    if text:
        raise McpConfigError(f"unsupported MCP transport type: {raw!r}")
    return "sse" if has_url else "stdio"


def _string_map(value: Any, field: str) -> dict:
    if value is None or value == "":
        return {}
    if not isinstance(value, dict):
        raise McpConfigError(f"{field} must be an object of string keys and values")
    out = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise McpConfigError(f"{field} keys must be non-empty strings")
        if item is None:
            continue
        out[key] = str(item)
    return out


def _string_list(value: Any, field: str) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [part for part in value.replace(",", " ").split() if part]
    if not isinstance(value, list):
        raise McpConfigError(f"{field} must be a list of strings")
    out = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(item if isinstance(item, str) else str(item))
    return out


def validate_server(cfg: dict) -> dict:
    """Return a normalized server dict, or raise McpConfigError."""
    if not isinstance(cfg, dict):
        raise McpConfigError("server config must be an object")

    name = str(cfg.get("name") or "").strip()
    if not name:
        raise McpConfigError("server name is required")
    if not _NAME_RE.match(name):
        raise McpConfigError(
            "server name must start with a letter or digit and contain only "
            "letters, digits, dots, underscores, or hyphens"
        )

    url = str(cfg.get("url") or "").strip()
    transport = normalize_transport(cfg.get("type"), has_url=bool(url))

    command = str(cfg.get("command") or "").strip()
    args = _string_list(cfg.get("args"), "args")
    env = _string_map(cfg.get("env"), "env")
    headers = _string_map(cfg.get("headers"), "headers")
    scope = str(cfg.get("scope") or "").strip()
    prefix = str(cfg.get("tool_name_prefix") or "")
    disabled = mcp_is_disabled(cfg)

    timeout = cfg.get("timeout", None)
    if timeout is None or timeout == "":
        timeout = None
    else:
        try:
            timeout = int(timeout)
        except (TypeError, ValueError) as exc:
            raise McpConfigError("timeout must be a positive integer") from exc
        if timeout <= 0:
            raise McpConfigError("timeout must be a positive integer")

    if transport == "stdio":
        if not command:
            raise McpConfigError("stdio servers require a command")
        if url:
            raise McpConfigError("stdio servers cannot also set url")
    else:
        if not url:
            raise McpConfigError(f"{transport} servers require a url")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise McpConfigError("url must be an absolute http(s) URL")
        if command:
            raise McpConfigError(f"{transport} servers cannot also set command")

    extras = {
        key: value
        for key, value in cfg.items()
        if key not in _KNOWN_FIELDS and key not in _EPHEMERAL_FIELDS
    }

    entry = {"name": name, "type": transport, **extras}
    if transport == "stdio":
        entry["command"] = command
        if args:
            entry["args"] = args
        if env:
            entry["env"] = env
    else:
        entry["url"] = url
        if headers:
            entry["headers"] = headers
        if scope:
            entry["scope"] = scope
    if prefix:
        entry["tool_name_prefix"] = prefix
    if disabled:
        entry["disabled"] = True
    if timeout is not None:
        entry["timeout"] = timeout
    return entry


def mcp_config_path(workspace: Optional[str] = None) -> str:
    from common.state_dir import mcp_config_file

    if workspace:
        return str(mcp_config_file(base=workspace))
    return str(mcp_config_file())


def load_servers(workspace: Optional[str] = None) -> list:
    """Read servers from mcp.json. Missing file -> empty list. Does not boot."""
    from agent.tools.tool_manager import _normalize_mcp_configs

    path = mcp_config_path(workspace)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"mcp.json is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise McpConfigError(f"failed to read mcp.json: {exc}") from exc

    if not isinstance(data, dict):
        raise McpConfigError("mcp.json must be a JSON object")
    raw = data.get("mcpServers")
    if raw is None:
        raw = data.get("mcp_servers", data)
    return _normalize_mcp_configs(raw)


def _persistable(entry: dict) -> dict:
    return {
        key: value
        for key, value in entry.items()
        if key not in {"name"} | _EPHEMERAL_FIELDS and value not in (None, "", [], {})
    }


def save_servers(workspace: Optional[str], servers: list) -> list:
    """Validate and write the full set as {"mcpServers": {...}}."""
    if not isinstance(servers, list):
        raise McpConfigError("servers must be a list")

    existing = {item.get("name"): item for item in load_servers(workspace) if item.get("name")}
    normalized = []
    seen = set()
    for item in servers:
        merged = dict(existing.get((item or {}).get("name"), {}))
        if isinstance(item, dict):
            merged.update(item)
        entry = validate_server(merged)
        if entry["name"] in seen:
            raise McpConfigError(f"duplicate MCP server name: {entry['name']}")
        seen.add(entry["name"])
        normalized.append(entry)

    path = mcp_config_path(workspace)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    payload = {"mcpServers": {entry["name"]: _persistable(entry) for entry in normalized}}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)
    logger.info("[MCP] Wrote %s (%s server(s))", path, len(normalized))
    return normalized


def refresh_mcp_managers() -> None:
    """Ask every live ToolManager to pick up mcp.json changes."""
    from agent.tools.tool_manager import ToolManager

    for manager in ToolManager.instances():
        if not hasattr(manager, "refresh_mcp_if_changed") or not hasattr(manager, "_mcp_lock"):
            continue
        try:
            manager.refresh_mcp_if_changed()
        except Exception as exc:
            logger.warning("[MCP] refresh after save failed: %s", exc)


def list_servers_with_status(workspace: Optional[str] = None) -> dict:
    """Servers from disk plus ToolManager status. Never starts a server."""
    from agent.tools.tool_manager import ToolManager

    servers = load_servers(workspace)
    status_map = {}
    target = os.path.realpath(workspace) if workspace else None
    for manager in ToolManager.instances():
        if target and os.path.realpath(getattr(manager, "workspace_root", "")) != target:
            continue
        status_map.update(manager.list_mcp_status())
        if target:
            break

    out = []
    for cfg in servers:
        item = dict(cfg)
        if mcp_is_disabled(item):
            item["status"] = "disabled"
        else:
            item["status"] = status_map.get(item.get("name"), "idle")
        item["type"] = normalize_transport(item.get("type"), has_url=bool(item.get("url")))
        out.append(item)
    return {"path": mcp_config_path(workspace), "servers": out}


def probe_server(cfg: dict) -> dict:
    """Dry-run one config: handshake + list tools, then shut down. No persist."""
    from agent.tools.mcp.mcp_client import McpClient

    entry = validate_server(cfg)
    if mcp_is_disabled(entry):
        return {
            "ok": False,
            "error": "server is disabled",
            "tools": [],
            "needs_auth": False,
        }

    test_cfg = dict(entry)
    test_cfg.setdefault("timeout", 15)
    client = McpClient(test_cfg)
    try:
        if not client.initialize():
            needs_auth = bool(getattr(client, "needs_auth", False))
            return {
                "ok": False,
                "error": "needs authorization" if needs_auth else "initialization failed",
                "tools": [],
                "needs_auth": needs_auth,
            }
        tools = []
        for tool in client.list_tools() or []:
            tools.append({
                "name": tool.get("name", ""),
                "description": tool.get("description", "") or "",
            })
        return {"ok": True, "error": None, "tools": tools, "needs_auth": False}
    except Exception as exc:
        logger.warning("[MCP] test connection for %s failed: %s", entry.get("name"), exc)
        return {
            "ok": False,
            "error": str(exc),
            "tools": [],
            "needs_auth": bool(getattr(client, "needs_auth", False)),
        }
    finally:
        try:
            client.shutdown()
        except Exception:
            pass
