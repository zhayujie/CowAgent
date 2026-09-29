"""
Memory get tool

Allows agents to read specific sections from memory files
"""

import os

from agent.tools.base_tool import BaseTool


class MemoryGetTool(BaseTool):
    """Tool for reading memory file contents"""
    
    name: str = "memory_get"
    description: str = (
        "Read specific content from memory files. "
        "Use this to get full context from a memory file or specific line range."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the memory file (e.g. 'MEMORY.md', 'memory/2026-01-01.md')"
            },
            "start_line": {
                "type": "integer",
                "description": "Starting line number (optional, default: 1)",
                "default": 1
            },
            "num_lines": {
                "type": "integer",
                "description": "Number of lines to read (optional, reads all if not specified)"
            }
        },
        "required": ["path"]
    }
    
    def __init__(self, memory_manager):
        """
        Initialize memory get tool
        
        Args:
            memory_manager: MemoryManager instance
        """
        super().__init__()
        self.memory_manager = memory_manager

        from config import conf
        if conf().get("knowledge", True):
            self.description = (
                "Read specific content from memory or knowledge files. "
                "Use this to get full context from a memory file, knowledge page, or specific line range."
            )
            self.params = {**self.params}
            self.params["properties"] = {**self.params["properties"]}
            self.params["properties"]["path"] = {
                "type": "string",
                "description": "Relative path to the memory or knowledge file (e.g. 'MEMORY.md', 'memory/2026-01-01.md', 'knowledge/concepts/moe.md')"
            }
    
    def execute(self, args: dict):
        """
        Execute memory file read
        
        Args:
            args: Dictionary with path, start_line, num_lines
            
        Returns:
            ToolResult with file content
        """
        from agent.tools.base_tool import ToolResult
        
        path = args.get("path")
        start_line = args.get("start_line", 1)
        num_lines = args.get("num_lines")
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # Both line arguments come straight from the model, so coerce them the
        # way bash/search_files coerce an integer argument before using it.
        # Uncoerced, a string start_line -- a routine way to send a number --
        # raised TypeError that the blanket except below reported as
        # "Error reading memory file: '<' not supported between ...".
        if isinstance(start_line, float) and not start_line.is_integer():
            return ToolResult.fail(f"Error: start_line must be an integer, got: {start_line!r}")
        try:
            start_line = int(start_line)
        except (TypeError, ValueError):
            return ToolResult.fail(f"Error: start_line must be an integer, got: {start_line!r}")
        
        # num_lines is rejected when it is not a positive count rather than
        # treated as "read to the end". The old `if num_lines:` branch let a
        # negative value build an inverted range whose slice is empty, so the
        # tool answered success with a "Lines: 2-1" header and no body -- a
        # silent empty read the model has no way to tell from a real one. An
        # omitted (None) num_lines still means "read the rest".
        if num_lines is not None:
            if isinstance(num_lines, float) and not num_lines.is_integer():
                return ToolResult.fail(f"Error: num_lines must be an integer, got: {num_lines!r}")
            try:
                num_lines = int(num_lines)
            except (TypeError, ValueError):
                return ToolResult.fail(f"Error: num_lines must be an integer, got: {num_lines!r}")
            if num_lines <= 0:
                return ToolResult.fail("Error: num_lines must be a positive integer")
        
        try:
            workspace_dir = self.memory_manager.config.get_workspace()
            
            # Auto-prepend memory/ if not present and not absolute path
            # Exceptions: MEMORY.md in root, knowledge/ files at workspace root
            if not path.startswith('memory/') and not path.startswith('knowledge/') and not path.startswith('/') and path != 'MEMORY.md':
                path = f'memory/{path}'
            
            # Roots this path may legitimately resolve under. A "knowledge/"
            # path goes through state_dir, which sends an Agent with no private
            # copy of its own to the shared root — the same fallback sync()
            # indexes through. Resolving it under the workspace alone means the
            # "knowledge/..." key memory_search just returned cannot be opened
            # here, which is how such an Agent used to lose every knowledge
            # page it had just been told about (#3175 follow-up).
            allowed_roots = [workspace_dir]
            if path.startswith('knowledge/'):
                from common import state_dir
                knowledge_root = state_dir.knowledge_dir(base=workspace_dir)
                file_path = (knowledge_root / path[len('knowledge/'):]).resolve()
                allowed_roots.append(knowledge_root)
            else:
                file_path = (workspace_dir / path).resolve()

            # Use os.path.realpath + os.sep for cross-platform path validation.
            # str(Path).startswith(str + '/') fails on Windows where Path uses
            # backslashes — see MemoryService._resolve_path for the same pattern.
            # Traversal out of a root ("knowledge/../../etc/passwd") still fails
            # here, because the check runs on the resolved path.
            def _contained(real_path: str, root) -> bool:
                real_root = os.path.realpath(str(root))
                return real_path == real_root or real_path.startswith(real_root + os.sep)

            real_file = os.path.realpath(str(file_path))
            if not any(_contained(real_file, root) for root in allowed_roots):
                return ToolResult.fail("Error: Access denied: path outside workspace")
            
            if not file_path.exists():
                return ToolResult.fail(f"Error: File not found: {path}")
            
            content = file_path.read_text(encoding='utf-8')
            lines = content.split('\n')
            
            # Handle line range
            if start_line < 1:
                start_line = 1
            
            start_idx = start_line - 1
            
            if num_lines:
                end_idx = start_idx + num_lines
                selected_lines = lines[start_idx:end_idx]
            else:
                selected_lines = lines[start_idx:]
            
            result = '\n'.join(selected_lines)
            
            # Add metadata
            total_lines = len(lines)
            shown_lines = len(selected_lines)
            
            output = [
                f"File: {path}",
                f"Lines: {start_line}-{start_line + shown_lines - 1} (total: {total_lines})",
                "",
                result
            ]
            
            return ToolResult.success('\n'.join(output))
            
        except Exception as e:
            return ToolResult.fail(f"Error reading memory file: {str(e)}")
