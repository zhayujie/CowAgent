import importlib
import importlib.util
import threading
from pathlib import Path
from typing import Dict, Any, Type
from agent.tools.base_tool import BaseTool
from common.log import logger
from config import conf


def _normalize_mcp_configs(raw) -> list:
    """
    Convert MCP server config to internal list format.
    Supports:
      - list format (mcp_servers):  [{"name": "x", "type": "stdio", ...}]
      - dict format (mcpServers):   {"x": {"command": "npx", ...}}
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        result = []
        for name, cfg in raw.items():
            entry = {"name": name, **cfg}
            if "type" not in entry:
                entry["type"] = "sse" if "url" in entry else "stdio"
            result.append(entry)
        return result
    return []


class ToolManager:
    """
    Tool manager for managing tools.
    """
    _instance = None

    def __new__(cls):
        """Singleton pattern to ensure only one instance of ToolManager exists."""
        if cls._instance is None:
            cls._instance = super(ToolManager, cls).__new__(cls)
            cls._instance.tool_classes = {}  # Store tool classes instead of instances
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # Initialize only once
        if not hasattr(self, 'tool_classes'):
            self.tool_classes = {}  # Dictionary to store tool classes
        if not hasattr(self, '_mcp_registry'):
            self._mcp_registry = None  # Lazy init: only created when MCP servers are configured
        if not hasattr(self, '_mcp_tool_instances'):
            self._mcp_tool_instances: dict = {}  # tool_name -> McpTool instance
        if not hasattr(self, '_mcp_lock'):
            # Guards _mcp_loaded check-then-set so concurrent callers
            # don't trigger duplicate background loaders.
            self._mcp_lock = threading.Lock()
        if not hasattr(self, '_mcp_loaded'):
            # Idempotency flag. Flipped to True the moment the first loader
            # is dispatched (synchronously, inside _mcp_lock). Subsequent
            # _load_mcp_tools() calls become no-ops, so per-session agent
            # initialization never re-forks MCP subprocesses.
            self._mcp_loaded = False
        if not hasattr(self, '_mcp_status'):
            # server_name -> "pending" / "ready" / "failed"
            # Useful for UI / introspection while async loading is in progress.
            self._mcp_status: dict = {}
        if not hasattr(self, '_mcp_signature'):
            # (mtime, sha256) of mcp.json the last time we loaded.
            # Used by refresh_mcp_if_changed() to skip re-parsing when nothing changed.
            self._mcp_signature: tuple = (None, None)
        if not hasattr(self, '_mcp_active_configs'):
            # server_name -> normalized config dict, for diff-based reload.
            self._mcp_active_configs: dict = {}

    def load_tools(self, tools_dir: str = "", config_dict=None):
        """
        Load tools from both directory and configuration.

        :param tools_dir: Directory to scan for tool modules
        """
        if tools_dir:
            self._load_tools_from_directory(tools_dir)
            self._configure_tools_from_config()
        else:
            self._load_tools_from_init()
            self._configure_tools_from_config(config_dict)

        self._load_mcp_tools()

    def _load_tools_from_init(self) -> bool:
        """
        Load tool classes from tools.__init__.__all__

        :return: True if tools were loaded, False otherwise
        """
        try:
            # Try to import the tools package
            tools_package = importlib.import_module("agent.tools")

            # Check if __all__ is defined
            if hasattr(tools_package, "__all__"):
                tool_classes = tools_package.__all__

                # Import each tool class directly from the tools package
                for class_name in tool_classes:
                    try:
                        # Skip base classes
                        if class_name in ["BaseTool", "ToolManager"]:
                            continue

                        # Get the class directly from the tools package
                        if hasattr(tools_package, class_name):
                            cls = getattr(tools_package, class_name)

                            if (
                                    isinstance(cls, type)
                                    and issubclass(cls, BaseTool)
                                    and cls != BaseTool
                            ):
                                try:
                                    # Skip tools that need special initialization
                                    if class_name in ["MemorySearchTool", "MemoryGetTool"]:
                                        logger.debug(f"Skipped tool {class_name} (requires memory_manager)")
                                        continue
                                    # McpTool instances are registered dynamically via _load_mcp_tools()
                                    if class_name == "McpTool":
                                        logger.debug(f"Skipped tool {class_name} (registered dynamically via mcp_servers config)")
                                        continue
                                    
                                    # Create a temporary instance to get the name
                                    temp_instance = cls()
                                    tool_name = temp_instance.name
                                    # Store the class, not the instance
                                    self.tool_classes[tool_name] = cls
                                    logger.debug(f"Loaded tool: {tool_name} from class {class_name}")
                                except ImportError as e:
                                    # Handle missing dependencies with helpful messages
                                    error_msg = str(e)
                                    if "playwright" in error_msg:
                                        logger.warning(
                                            f"[ToolManager] Browser tool not loaded - missing dependencies.\n"
                                            f"  To enable browser tool, run:\n"
                                            f"    pip install playwright\n"
                                            f"    playwright install chromium"
                                        )
                                    elif "markdownify" in error_msg:
                                        logger.warning(
                                            f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                            f"  Install with: pip install markdownify"
                                        )
                                    else:
                                        logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                                except Exception as e:
                                    logger.error(f"Error initializing tool class {cls.__name__}: {e}")
                    except Exception as e:
                        logger.error(f"Error importing class {class_name}: {e}")

                return len(self.tool_classes) > 0
            return False
        except ImportError:
            logger.warning("Could not import agent.tools package")
            return False
        except Exception as e:
            logger.error(f"Error loading tools from __init__.__all__: {e}")
            return False

    def _load_tools_from_directory(self, tools_dir: str):
        """Dynamically load tool classes from directory"""
        tools_path = Path(tools_dir)

        # Traverse all .py files
        for py_file in tools_path.rglob("*.py"):
            # Skip initialization files and base tool files
            if py_file.name in ["__init__.py", "base_tool.py", "tool_manager.py"]:
                continue

            # Get module name
            module_name = py_file.stem

            try:
                # Load module directly from file
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Find tool classes in the module
                    for attr_name in dir(module):
                        cls = getattr(module, attr_name)
                        if (
                                isinstance(cls, type)
                                and issubclass(cls, BaseTool)
                                and cls != BaseTool
                        ):
                            try:
                                # Skip memory tools (they need special initialization with memory_manager)
                                if attr_name in ["MemorySearchTool", "MemoryGetTool"]:
                                    logger.debug(f"Skipped tool {attr_name} (requires memory_manager)")
                                    continue
                                
                                # Create a temporary instance to get the name
                                temp_instance = cls()
                                tool_name = temp_instance.name
                                # Store the class, not the instance
                                self.tool_classes[tool_name] = cls
                            except ImportError as e:
                                # Handle missing dependencies with helpful messages
                                error_msg = str(e)
                                if "playwright" in error_msg:
                                    logger.warning(
                                        f"[ToolManager] Browser tool not loaded - missing dependencies.\n"
                                        f"  To enable browser tool, run:\n"
                                        f"    pip install playwright\n"
                                        f"    playwright install chromium"
                                    )
                                elif "markdownify" in error_msg:
                                    logger.warning(
                                        f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                        f"  Install with: pip install markdownify"
                                    )
                                else:
                                    logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                            except Exception as e:
                                logger.error(f"Error initializing tool class {cls.__name__}: {e}")
            except Exception as e:
                print(f"Error importing module {py_file}: {e}")

    def _configure_tools_from_config(self, config_dict=None):
        """Configure tool classes based on configuration file"""
        try:
            # Get tools configuration
            tools_config = config_dict or conf().get("tools", {})

            # Record tools that are configured but not loaded
            missing_tools = []

            # Store configurations for later use when instantiating
            self.tool_configs = tools_config

            # Check which configured tools are missing
            for tool_name in tools_config:
                if tool_name not in self.tool_classes:
                    missing_tools.append(tool_name)

            # If there are missing tools, record warnings
            if missing_tools:
                for tool_name in missing_tools:
                    if tool_name == "browser":
                        logger.warning(
                            f"[ToolManager] Browser tool is configured but not loaded.\n"
                            f"  To enable browser tool, run:\n"
                            f"    pip install playwright\n"
                            f"    playwright install chromium"
                        )
                    elif tool_name == "google_search":
                        logger.warning(
                            f"[ToolManager] Google Search tool is configured but may need API key.\n"
                            f"  Get API key from: https://serper.dev\n"
                            f"  Configure in config.json: tools.google_search.api_key"
                        )
                    else:
                        logger.warning(f"[ToolManager] Tool '{tool_name}' is configured but could not be loaded.")

        except Exception as e:
            logger.error(f"Error configuring tools from config: {e}")

    def _mcp_json_path(self) -> str:
        import os
        workspace = os.path.expanduser(conf().get("agent_workspace", "~/cow"))
        return os.path.join(workspace, "mcp.json")

    def _read_mcp_json_signature(self):
        """
        Return (mtime, sha256_of_bytes) for ~/cow/mcp.json without parsing.
        Returns (None, None) if the file doesn't exist or is unreadable.
        Cheap enough (one stat + one small read) to call on every agent init.
        """
        import os
        import hashlib
        path = self._mcp_json_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return (None, None)
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return (mtime, None)
        return (mtime, digest)

    def _load_mcp_configs(self) -> list:
        """
        Load MCP server configs with priority:
          1. ~/cow/mcp.json  (supports both mcpServers and mcp_servers keys)
          2. config.json mcp_servers field (fallback)
        """
        import os
        import json as _json

        mcp_json_path = self._mcp_json_path()

        if os.path.exists(mcp_json_path):
            try:
                with open(mcp_json_path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                raw = data.get("mcpServers") or data.get("mcp_servers") or data
                logger.info(f"[ToolManager] Loading MCP config from {mcp_json_path}")
                return _normalize_mcp_configs(raw)
            except Exception as e:
                logger.warning(f"[ToolManager] Failed to read {mcp_json_path}: {e}, falling back to config.json")

        raw = conf().get("mcp_servers", [])
        return _normalize_mcp_configs(raw)

    def _load_mcp_tools(self):
        """
        Trigger MCP tool loading in a background thread (idempotent).

        Returns immediately. Booting MCP servers (npx, uvx, etc.) takes
        seconds to tens of seconds on first run, which would otherwise
        block agent initialization and the user's first message.
        Built-in tools work fine without MCP, so we let the agent serve
        traffic right away and let MCP servers come online in the
        background. Per-session agents read a snapshot of whatever is
        ready at construction time and gracefully ignore the rest.
        """
        with self._mcp_lock:
            if self._mcp_loaded:
                return
            mcp_servers_config = self._load_mcp_configs()
            # Snapshot the signature now so future refresh_mcp_if_changed()
            # calls can short-circuit when nothing has changed on disk.
            self._mcp_signature = self._read_mcp_json_signature()
            self._mcp_active_configs = {
                cfg.get("name", "<unnamed>"): cfg for cfg in mcp_servers_config
            }
            if not mcp_servers_config:
                # Mark as loaded even when there is nothing to load,
                # so we don't re-read the config file on every call.
                self._mcp_loaded = True
                return

            # Mark pending immediately so list_mcp_status() callers see
            # the in-progress state instead of an empty dict.
            for cfg in mcp_servers_config:
                name = cfg.get("name", "<unnamed>")
                self._mcp_status[name] = "pending"

            self._mcp_loaded = True
            threading.Thread(
                target=self._load_mcp_tools_async,
                args=(mcp_servers_config,),
                daemon=True,
                name="mcp-loader",
            ).start()
            logger.info(
                f"[ToolManager] MCP loading started in background "
                f"({len(mcp_servers_config)} server(s) configured)"
            )

    def refresh_mcp_if_changed(self):
        """
        Cheap check whether ~/cow/mcp.json has changed since last load.
        If it has, do a diff-based reload: start newly added servers,
        shut down removed ones, and restart any whose config was edited.
        Untouched servers are left running.

        Designed to be called on every agent creation. The fast path is
        a single os.stat() — completely free when nothing has changed.
        """
        with self._mcp_lock:
            new_sig = self._read_mcp_json_signature()
            if new_sig == self._mcp_signature:
                return  # no-op fast path

            try:
                new_configs = self._load_mcp_configs()
            except Exception as e:
                logger.warning(f"[ToolManager] MCP reload — failed to parse config: {e}")
                return

            new_by_name = {
                cfg.get("name", "<unnamed>"): cfg for cfg in new_configs
            }
            old_by_name = self._mcp_active_configs

            added = [n for n in new_by_name if n not in old_by_name]
            removed = [n for n in old_by_name if n not in new_by_name]
            changed = [
                n for n in new_by_name
                if n in old_by_name and new_by_name[n] != old_by_name[n]
            ]

            if not (added or removed or changed):
                # Signature drifted but content is logically identical
                # (e.g. user re-saved the file without edits). Just sync.
                self._mcp_signature = new_sig
                return

            logger.info(
                f"[ToolManager] mcp.json changed — "
                f"adding={added}, removing={removed}, restarting={changed}"
            )

            # Tear down removed + changed servers (changed ones get restarted below)
            for name in removed + changed:
                self._teardown_mcp_server(name)

            # Spin up newly added + changed servers in the background
            to_start = [new_by_name[n] for n in added + changed]
            if to_start:
                for cfg in to_start:
                    self._mcp_status[cfg.get("name", "<unnamed>")] = "pending"
                threading.Thread(
                    target=self._load_mcp_tools_async,
                    args=(to_start,),
                    daemon=True,
                    name="mcp-loader-reload",
                ).start()

            self._mcp_active_configs = new_by_name
            self._mcp_signature = new_sig

    def _teardown_mcp_server(self, server_name: str):
        """Shut down one MCP server and drop its tools from the registry."""
        if self._mcp_registry is None:
            return
        client = None
        with self._mcp_registry._registry_lock:
            client = self._mcp_registry._clients.pop(server_name, None)
        if client is not None:
            try:
                client.shutdown()
            except Exception as e:
                logger.warning(f"[MCP] Error shutting down '{server_name}': {e}")
        # Drop tools that belonged to this server.
        for tool_name in list(self._mcp_tool_instances.keys()):
            tool = self._mcp_tool_instances.get(tool_name)
            if tool is not None and getattr(tool, "server_name", None) == server_name:
                self._mcp_tool_instances.pop(tool_name, None)
        self._mcp_status.pop(server_name, None)

    def _load_mcp_tools_async(self, mcp_servers_config):
        """
        Background worker: bring up each MCP server one-by-one and
        publish ready tools to _mcp_tool_instances as they come online.

        Server failures are isolated — one bad server cannot block
        the others, and never raises out of the worker thread.
        """
        try:
            from agent.tools.mcp.mcp_client import McpClient, McpClientRegistry
            from agent.tools.mcp.mcp_tool import McpTool

            registry = McpClientRegistry()
            self._mcp_registry = registry

            for cfg in mcp_servers_config:
                server_name = cfg.get("name", "<unnamed>")
                try:
                    client = McpClient(cfg)
                    if not client.initialize():
                        self._mcp_status[server_name] = "failed"
                        logger.warning(
                            f"[MCP] Server '{server_name}' failed to initialize — skipping"
                        )
                        continue

                    tool_schemas = client.list_tools()
                    added = []
                    for schema in tool_schemas:
                        tool_name = schema.get("name", "")
                        if not tool_name:
                            continue
                        mcp_tool = McpTool(client, schema, server_name)
                        # Atomic dict assignment is GIL-safe; readers iterate
                        # over a list() snapshot to avoid concurrent mutation.
                        self._mcp_tool_instances[tool_name] = mcp_tool
                        added.append(tool_name)

                    # Register client into the shared registry only after its
                    # tools are visible, so callers never see a half-loaded server.
                    with registry._registry_lock:
                        registry._clients[server_name] = client
                    self._mcp_status[server_name] = "ready"
                    logger.info(
                        f"[MCP] Server '{server_name}' ready — "
                        f"{len(added)} tool(s): {added}"
                    )
                except Exception as e:
                    self._mcp_status[server_name] = "failed"
                    logger.warning(f"[MCP] Server '{server_name}' load failed: {e}")

            ready = sum(1 for s in self._mcp_status.values() if s == "ready")
            total = len(self._mcp_status)
            logger.info(
                f"[ToolManager] MCP loading complete: "
                f"{ready}/{total} server(s) ready, "
                f"{len(self._mcp_tool_instances)} tool(s) available"
            )
        except Exception as e:
            logger.warning(f"[ToolManager] MCP background loader crashed: {e}")

    def list_mcp_status(self) -> dict:
        """Return {server_name: status} snapshot for UI / debugging."""
        return dict(self._mcp_status)

    def sync_mcp_into_agent(self, agent) -> tuple:
        """
        Reconcile a live agent's tool collection with the current MCP tool registry.

        Adds tools that finished loading after the agent was created,
        and removes tools whose MCP server was torn down. Built-in tools
        on the agent are left untouched.

        Handles both representations CowAgent uses:
          - Agent.tools: list[BaseTool]               (default Agent class)
          - AgentStream.tools: dict[str, BaseTool]    (streaming agent)

        Returns (added_names, removed_names) for logging.
        """
        if agent is None or not hasattr(agent, "tools"):
            return ([], [])

        from agent.tools.mcp.mcp_tool import McpTool
        current = self._mcp_tool_instances
        registry_names = set(current.keys())

        agent_tools = agent.tools

        if isinstance(agent_tools, dict):
            agent_mcp_names = {
                name for name, tool in agent_tools.items()
                if isinstance(tool, McpTool)
            }
            added = registry_names - agent_mcp_names
            removed = agent_mcp_names - registry_names
            if not (added or removed):
                return ([], [])
            for name in added:
                agent_tools[name] = current[name]
            for name in removed:
                agent_tools.pop(name, None)

        elif isinstance(agent_tools, list):
            agent_mcp_names = {
                t.name for t in agent_tools if isinstance(t, McpTool)
            }
            added = registry_names - agent_mcp_names
            removed = agent_mcp_names - registry_names
            if not (added or removed):
                return ([], [])
            if removed:
                agent.tools = [
                    t for t in agent_tools
                    if not (isinstance(t, McpTool) and t.name in removed)
                ]
            for name in added:
                agent.tools.append(current[name])

        else:
            return ([], [])

        return (sorted(added), sorted(removed))

    def create_tool(self, name: str) -> BaseTool:
        """
        Get a new instance of a tool by name.

        :param name: The name of the tool to get.
        :return: A new instance of the tool or None if not found.
        """
        tool_class = self.tool_classes.get(name)
        if tool_class:
            # Create a new instance
            tool_instance = tool_class()

            # Apply configuration if available
            if hasattr(self, 'tool_configs') and name in self.tool_configs:
                tool_instance.config = self.tool_configs[name]

            return tool_instance

        # Fall back to MCP tool instances
        mcp_tool = self._mcp_tool_instances.get(name)
        if mcp_tool:
            return mcp_tool

        return None

    def list_tools(self) -> dict:
        """
        Get information about all loaded tools.

        :return: A dictionary with tool information.
        """
        result = {}
        for name, tool_class in self.tool_classes.items():
            # Create a temporary instance to get schema
            temp_instance = tool_class()
            result[name] = {
                "description": temp_instance.description,
                "parameters": temp_instance.get_json_schema()
            }

        # Include MCP tool instances
        for name, mcp_tool in self._mcp_tool_instances.items():
            result[name] = {
                "description": mcp_tool.description,
                "parameters": mcp_tool.params,
            }

        return result

    def shutdown_mcp(self):
        """Shut down all MCP server clients."""
        if self._mcp_registry:
            self._mcp_registry.shutdown_all()
