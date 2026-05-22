"""
Environment Configuration Tool - Manage API keys and environment variables
"""

import os
import re
from typing import Dict, Any
from pathlib import Path

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
from common.utils import expand_path


# API Key 知识库：常见的环境变量及其描述
API_KEY_REGISTRY = {
    # AI 模型服务
    "OPENAI_API_KEY": "OpenAI API 密钥 (用于GPT模型、Embedding模型)",
    "GEMINI_API_KEY": "Google Gemini API 密钥",
    "CLAUDE_API_KEY": "Claude API 密钥 (用于Claude模型)",
    "LINKAI_API_KEY": "LinkAI智能体平台 API 密钥，支持多种模型切换",
    # 搜索服务
    "BOCHA_API_KEY": "博查 AI 搜索 API 密钥 ",
}

class EnvConfig(BaseTool):
    """Tool for managing environment variables (API keys, etc.)"""
    
    name: str = "env_config"
    description: str = (
        "Manage API keys and skill configurations securely. "
        "Use this tool when user wants to configure API keys (like BOCHA_API_KEY, OPENAI_API_KEY), "
        "view configured keys, or manage skill settings. "
        "Actions: 'set' (add/update key), 'get' (view specific key), 'list' (show all configured keys), 'delete' (remove key). "
        "Values are automatically masked for security. Changes take effect immediately via hot reload."
    )
    
    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action to perform: 'set', 'get', 'list', 'delete'",
                "enum": ["set", "get", "list", "delete"]
            },
            "key": {
                "type": "string",
                "description": (
                    "Environment variable key name. Common keys:\n"
                    "- OPENAI_API_KEY: OpenAI API (GPT models)\n"
                    "- OPENAI_API_BASE: OpenAI API base URL\n"
                    "- CLAUDE_API_KEY: Anthropic Claude API\n"
                    "- GEMINI_API_KEY: Google Gemini API\n"
                    "- LINKAI_API_KEY: LinkAI platform\n"
                    "- BOCHA_API_KEY: Bocha AI search (博查搜索)\n"
                    "Use exact key names (case-sensitive, all uppercase with underscores)"
                )
            },
            "value": {
                "type": "string",
                "description": "Value to set for the environment variable (for 'set' action)"
            }
        },
        "required": ["action"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        # Store env config in ~/.cow directory (outside workspace for security)
        self.env_dir = expand_path("~/.cow")
        self.env_path = os.path.join(self.env_dir, '.env')
        self.agent_bridge = self.config.get("agent_bridge")  # Reference to AgentBridge for hot reload
        # Don't create .env file in __init__ to avoid issues during tool discovery
        # It will be created on first use in execute()
    
    def _ensure_env_file(self):
        """Ensure the .env file exists"""
        # Create ~/.cow directory if it doesn't exist
        os.makedirs(self.env_dir, exist_ok=True)
        
        if not os.path.exists(self.env_path):
            Path(self.env_path).touch()
            logger.info(f"[EnvConfig] Created .env file at {self.env_path}")
    
    def _mask_value(self, value: str) -> str:
        """Mask sensitive parts of a value for logging"""
        if not value or len(value) <= 10:
            return "***"
        return f"{value[:6]}***{value[-4:]}"
    
    def _read_env_file(self) -> Dict[str, str]:
        """Read all key-value pairs from .env file"""
        env_vars = {}
        if os.path.exists(self.env_path):
            with open(self.env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    # Parse KEY=VALUE
                    match = re.match(r'^([^=]+)=(.*)$', line)
                    if match:
                        key, value = match.groups()
                        env_vars[key.strip()] = value.strip()
        return env_vars
    
    def _write_env_file(self, env_vars: Dict[str, str]):
        """Write all key-value pairs to .env file"""
        with open(self.env_path, 'w', encoding='utf-8') as f:
            f.write("# Environment variables for agent skills\n")
            f.write("# Auto-managed by env_config tool\n\n")
            for key, value in sorted(env_vars.items()):
                f.write(f"{key}={value}\n")
    
    def _reload_env(self):
        """Reload environment variables from .env file"""
        env_vars = self._read_env_file()
        for key, value in env_vars.items():
            os.environ[key] = value
        logger.debug(f"[EnvConfig] Reloaded {len(env_vars)} environment variables")
    
    def _refresh_skills(self):
        """Refresh skills after environment variable changes"""
        if self.agent_bridge:
            try:
                # Reload .env file
                self._reload_env()
                
                # Refresh skills in all agent instances
                refreshed = self.agent_bridge.refresh_all_skills()
                logger.info(f"[EnvConfig] Refreshed skills in {refreshed} agent instance(s)")
                return True
            except Exception as e:
                logger.warning(f"[EnvConfig] Failed to refresh skills: {e}")
                return False
        return False
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute environment configuration operation
        
        :param args: Contains action, key, and value parameters
        :return: Result of the operation
        """
        # Ensure .env file exists on first use
        self._ensure_env_file()
        
        action = args.get("action")
        key = args.get("key")
        value = args.get("value")
        
        try:
            if action == "set":
                if not key or not value:
                    return ToolResult.fail("Error: 'key' and 'value' are required for 'set' action.")
                
                # Read current env vars
                env_vars = self._read_env_file()
                
                # Update the key
                env_vars[key] = value
                
                # Write back to file
                self._write_env_file(env_vars)
                
                # Update current process env
                os.environ[key] = value
                
                logger.info(f"[EnvConfig] Set {key}={self._mask_value(value)}")
                
                # Try to refresh skills immediately
                refreshed = self._refresh_skills()
                
                result = {
                    "message": f"Successfully set {key}",
                    "key": key,
                    "value": self._mask_value(value),
                }
                
                if refreshed:
                    result["note"] = "✅ Skills refreshed automatically - changes are now active"
                else:
                    result["note"] = "⚠️ Skills not refreshed - restart agent to load new skills"
                
                return ToolResult.success(result)
            
            elif action == "get":
                if not key:
                    return ToolResult.fail("Error: 'key' is required for 'get' action.")
                
                # Check in file first, then in current env
                env_vars = self._read_env_file()
                value = env_vars.get(key) or os.getenv(key)
                
                # Get description from registry
                description = API_KEY_REGISTRY.get(key, "未知用途的环境变量")
                
                if value is not None:
                    logger.info(f"[EnvConfig] Got {key}={self._mask_value(value)}")
                    return ToolResult.success({
                        "key": key,
                        "value": self._mask_value(value),
                        "description": description,
                        "exists": True,
                        "note": f"Value is masked for security. In bash, use ${key} directly — it is auto-injected."
                    })
                else:
                    return ToolResult.success({
                        "key": key,
                        "description": description,
                        "exists": False,
                        "message": f"Environment variable '{key}' is not set"
                    })
            
            elif action == "list":
                env_vars = self._read_env_file()
                
                # Build detailed variable list with descriptions
                variables_with_info = {}
                for key, value in env_vars.items():
                    variables_with_info[key] = {
                        "value": self._mask_value(value),
                        "description": API_KEY_REGISTRY.get(key, "未知用途的环境变量")
                    }
                
                logger.info(f"[EnvConfig] Listed {len(env_vars)} environment variables")
                
                if not env_vars:
                    return ToolResult.success({
                        "message": "No environment variables configured",
                        "variables": {},
                        "note": "常用的 API 密钥可以通过 env_config(action='set', key='KEY_NAME', value='your-key') 来配置"
                    })
                
                return ToolResult.success({
                    "message": f"Found {len(env_vars)} environment variable(s)",
                    "variables": variables_with_info
                })
            
            elif action == "delete":
                if not key:
                    return ToolResult.fail("Error: 'key' is required for 'delete' action.")
                
                # Read current env vars
                env_vars = self._read_env_file()
                
                if key not in env_vars:
                    return ToolResult.success({
                        "message": f"Environment variable '{key}' was not set",
                        "key": key
                    })
                
                # Remove the key
                del env_vars[key]
                
                # Write back to file
                self._write_env_file(env_vars)
                
                # Remove from current process env
                if key in os.environ:
                    del os.environ[key]
                
                logger.info(f"[EnvConfig] Deleted {key}")
                
                # Try to refresh skills immediately
                refreshed = self._refresh_skills()
                
                result = {
                    "message": f"Successfully deleted {key}",
                    "key": key,
                }
                
                if refreshed:
                    result["note"] = "✅ Skills refreshed automatically - changes are now active"
                else:
                    result["note"] = "⚠️ Skills not refreshed - restart agent to apply changes"
                
                return ToolResult.success(result)
            
            else:
                return ToolResult.fail(f"Error: Unknown action '{action}'. Use 'set', 'get', 'list', or 'delete'.")
        
        except Exception as e:
            logger.error(f"[EnvConfig] Error: {e}", exc_info=True)
            return ToolResult.fail(f"EnvConfig tool error: {str(e)}")
