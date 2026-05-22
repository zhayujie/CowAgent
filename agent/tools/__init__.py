# Import base tool
from agent.tools.base_tool import BaseTool
from agent.tools.tool_manager import ToolManager

# Import file operation tools
from agent.tools.read.read import Read
from agent.tools.write.write import Write
from agent.tools.edit.edit import Edit
from agent.tools.bash.bash import Bash
from agent.tools.ls.ls import Ls
from agent.tools.send.send import Send

# Import memory tools
from agent.tools.memory.memory_search import MemorySearchTool
from agent.tools.memory.memory_get import MemoryGetTool

# Import tools with optional dependencies
def _import_optional_tools():
    """Import tools that have optional dependencies"""
    from common.log import logger
    tools = {}
    
    # EnvConfig Tool (requires python-dotenv)
    try:
        from agent.tools.env_config.env_config import EnvConfig
        tools['EnvConfig'] = EnvConfig
    except ImportError as e:
        logger.error(
            f"[Tools] EnvConfig tool not loaded - missing dependency: {e}\n"
            f"  To enable environment variable management, run:\n"
            f"    pip install python-dotenv>=1.0.0"
        )
    except Exception as e:
        logger.error(f"[Tools] EnvConfig tool failed to load: {e}")
    
    # Scheduler Tool (requires croniter)
    try:
        from agent.tools.scheduler.scheduler_tool import SchedulerTool
        tools['SchedulerTool'] = SchedulerTool
    except ImportError as e:
        logger.error(
            f"[Tools] Scheduler tool not loaded - missing dependency: {e}\n"
            f"  To enable scheduled tasks, run:\n"
            f"    pip install croniter>=2.0.0"
        )
    except Exception as e:
        logger.error(f"[Tools] Scheduler tool failed to load: {e}")

    # WebSearch Tool (conditionally loaded based on API key availability at init time)
    try:
        from agent.tools.web_search.web_search import WebSearch
        tools['WebSearch'] = WebSearch
    except ImportError as e:
        logger.error(f"[Tools] WebSearch not loaded - missing dependency: {e}")
    except Exception as e:
        logger.error(f"[Tools] WebSearch failed to load: {e}")

    # WebFetch Tool
    try:
        from agent.tools.web_fetch.web_fetch import WebFetch
        tools['WebFetch'] = WebFetch
    except ImportError as e:
        logger.error(f"[Tools] WebFetch not loaded - missing dependency: {e}")
    except Exception as e:
        logger.error(f"[Tools] WebFetch failed to load: {e}")

    # Vision Tool (conditionally loaded based on API key availability)
    try:
        from agent.tools.vision.vision import Vision
        tools['Vision'] = Vision
    except ImportError as e:
        logger.error(f"[Tools] Vision not loaded - missing dependency: {e}")
    except Exception as e:
        logger.error(f"[Tools] Vision failed to load: {e}")

    return tools

# Load optional tools
_optional_tools = _import_optional_tools()
EnvConfig = _optional_tools.get('EnvConfig')
SchedulerTool = _optional_tools.get('SchedulerTool')
WebSearch = _optional_tools.get('WebSearch')
WebFetch = _optional_tools.get('WebFetch')
Vision = _optional_tools.get('Vision')
GoogleSearch = _optional_tools.get('GoogleSearch')
FileSave = _optional_tools.get('FileSave')
Terminal = _optional_tools.get('Terminal')


# BrowserTool (requires playwright)
def _import_browser_tool():
    from common.log import logger
    try:
        from agent.tools.browser.browser_tool import BrowserTool
        return BrowserTool
    except ImportError as e:
        logger.info(
            f"[Tools] BrowserTool not loaded - missing dependency: {e}\n"
            f"  To enable browser tool, run:\n"
            f"    pip install playwright\n"
            f"    playwright install chromium"
        )
        return None
    except Exception as e:
        logger.error(f"[Tools] BrowserTool failed to load: {e}")
        return None

BrowserTool = _import_browser_tool()

# MCP Tools (no extra dependencies, loaded on demand)
def _import_mcp_tools():
    """导入 MCP 工具模块（无额外依赖，按需加载）"""
    from common.log import logger
    try:
        from agent.tools.mcp.mcp_tool import McpTool
        from agent.tools.mcp.mcp_client import McpClientRegistry
        return {'McpTool': McpTool, 'McpClientRegistry': McpClientRegistry}
    except Exception as e:
        logger.warning(f"[Tools] MCP tools not loaded: {e}")
        return {}

_mcp_tools = _import_mcp_tools()
McpTool = _mcp_tools.get('McpTool')
McpClientRegistry = _mcp_tools.get('McpClientRegistry')

# Export all tools (including optional ones that might be None)
__all__ = [
    'BaseTool',
    'ToolManager',
    'Read',
    'Write',
    'Edit',
    'Bash',
    'Ls',
    'Send',
    'MemorySearchTool',
    'MemoryGetTool',
    'EnvConfig',
    'SchedulerTool',
    'WebSearch',
    'WebFetch',
    'Vision',
    'BrowserTool',
    'McpTool',
]

"""
Tools module for Agent.
"""
