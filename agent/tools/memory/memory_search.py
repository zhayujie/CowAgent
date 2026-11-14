"""
Memory search tool

Allows agents to search their memory using semantic and keyword search
"""

from typing import Optional
from agent.tools.base_tool import BaseTool


class MemorySearchTool(BaseTool):
    """Tool for searching agent memory"""
    
    name: str = "memory_search"
    description: str = (
        "Search agent's long-term memory using semantic and keyword search. "
        "Use this to recall past conversations, preferences, and knowledge."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (can be natural language question or keywords)"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 10)",
                "default": 10
            },
            "min_score": {
                "type": "number",
                "description": "Minimum relevance score (0-1, default: 0.1)",
                "default": 0.1
            }
        },
        "required": ["query"]
    }
    
    def __init__(self, memory_manager, user_id: Optional[str] = None):
        """
        Initialize memory search tool
        
        Args:
            memory_manager: MemoryManager instance
            user_id: Optional user ID for scoped search
        """
        super().__init__()
        self.memory_manager = memory_manager
        self.user_id = user_id

        from config import conf
        if conf().get("knowledge", True):
            self.description = (
                "Search agent's long-term memory and knowledge base using semantic and keyword search. "
                "Use this to recall past conversations, preferences, and knowledge pages."
            )
    
    def execute(self, args: dict):
        """
        Execute memory search
        
        Args:
            args: Dictionary with query, max_results, min_score
            
        Returns:
            ToolResult with formatted search results
        """
        from agent.tools.base_tool import ToolResult
        import asyncio
        
        query = args.get("query")
        max_results = args.get("max_results", 10)
        min_score = args.get("min_score", 0.1)
        
        if not query:
            return ToolResult.fail("Error: query parameter is required")
        
        try:
            # Run async search in sync context
            results = asyncio.run(self.memory_manager.search(
                query=query,
                user_id=self.user_id,
                max_results=max_results,
                min_score=min_score,
                include_shared=getattr(self, "include_shared", True),
                include_knowledge=getattr(self, "include_knowledge", False),
            ))
            
            if not results:
                # Return clear message that no memories exist yet
                # This prevents infinite retry loops
                target = (f"memory/users/{self.user_id}/MEMORY.md or "
                          f"memory/users/{self.user_id}/YYYY-MM-DD.md"
                          if self.user_id and not getattr(self, "include_shared", True)
                          else "MEMORY.md or memory/YYYY-MM-DD.md")
                return ToolResult.success(
                    f"No memories found for '{query}'. "
                    f"This is normal if no memories have been stored yet. "
                    f"You can store new memories by writing to {target}."
                )
            
            # Format results
            output = [f"Found {len(results)} relevant memories:\n"]

            # The knowledge section of the prompt names this root too, but it is
            # skipped entirely when there is no index.md, and these paths are
            # useless to a reader who does not know what they are relative to.
            hint = self._knowledge_root_hint(results)
            if hint:
                output.append(hint)
            
            for i, result in enumerate(results, 1):
                output.append(f"\n{i}. {result.path} (lines {result.start_line}-{result.end_line})")
                output.append(f"   Score: {result.score:.3f}")
                output.append(f"   Snippet: {result.snippet}")
            
            return ToolResult.success("\n".join(output))
            
        except Exception as e:
            return ToolResult.fail(f"Error searching memory: {str(e)}")

    def _knowledge_root_hint(self, results) -> Optional[str]:
        """Where the "knowledge/..." paths below actually live, when that is not
        under the workspace every other tool resolves against.

        An Agent with no knowledge/ of its own reads the shared copy, so these
        paths are relative to the shared root. Said once for the whole result
        set rather than per hit, and only when the two roots differ, so the
        common single-Agent install sees nothing new.
        """
        if not any(str(r.path).startswith("knowledge/") for r in results):
            return None
        try:
            import os
            from common import state_dir

            workspace = str(self.memory_manager.config.get_workspace())
            root = str(state_dir.knowledge_dir(base=workspace))
            own = os.path.join(workspace, "knowledge")
            if os.path.realpath(root) == os.path.realpath(own):
                return None
            return f'("knowledge/..." below is relative to {root})\n'
        except Exception:
            return None
