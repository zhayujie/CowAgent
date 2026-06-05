"""
Write tool - Write file content
Creates or overwrites files, automatically creates parent directories
"""

import os
from typing import Dict, Any
from pathlib import Path

from agent.tools.base_tool import BaseTool, ToolResult
from common.utils import expand_path


class Write(BaseTool):
    """Tool for writing file content"""
    
    name: str = "write"
    description: str = "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories. IMPORTANT: Single write should not exceed 10KB. For large files, create a skeleton first, then use edit to add content in chunks."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (relative or absolute)"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["path", "content"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.memory_manager = self.config.get("memory_manager", None)
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file write operation
        
        :param args: Contains file path and content
        :return: Operation result
        """
        path = args.get("path", "").strip()
        content = args.get("content", "")
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # Resolve path
        absolute_path = self._resolve_path(path)
        
        try:
            # Create parent directory (if needed)
            parent_dir = os.path.dirname(absolute_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            # Check if this is a memory file and append session comment
            is_memory_file = self._is_memory_file(path)
            if is_memory_file:
                session_id = self._get_current_session_id()
                if session_id:
                    # Append session comment if not already present
                    if f"<!-- session: {session_id} -->" not in content:
                        if not content.endswith('\n'):
                            content += '\n'
                        content += f"\n<!-- session: {session_id} -->\n"
            
            # Write file
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Get bytes written
            bytes_written = len(content.encode('utf-8'))
            
            # Auto-sync to memory database if this is a memory file
            if self.memory_manager and is_memory_file:
                self.memory_manager.mark_dirty()
            
            result = {
                "message": f"Successfully wrote {bytes_written} bytes to {path}",
                "path": path,
                "bytes_written": bytes_written
            }
            
            return ToolResult.success(result)
            
        except PermissionError:
            return ToolResult.fail(f"Error: Permission denied writing to {path}")
        except Exception as e:
            return ToolResult.fail(f"Error writing file: {str(e)}")
    
    def _is_memory_file(self, path: str) -> bool:
        """Check if path is a memory-related file"""
        path_lower = path.lower()
        return (
            'memory/' in path_lower or 
            'knowledge/' in path_lower or 
            path_lower.endswith('memory.md') or
            path_lower == 'memory.md'
        )
    
    def _get_current_session_id(self) -> str:
        """Get current session ID from context"""
        try:
            if hasattr(self, 'context') and self.context:
                return getattr(self.context, '_current_session_id', None)
        except Exception:
            pass
        return None
    
    def _resolve_path(self, path: str) -> str:
        """
        Resolve path to absolute path
        
        :param path: Relative or absolute path
        :return: Absolute path
        """
        # Expand ~ to user home directory
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))
