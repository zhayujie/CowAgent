from enum import Enum
from typing import Any, Optional
from common.log import logger
import copy


class ToolStage(Enum):
    """Enum representing tool decision stages"""
    PRE_PROCESS = "pre_process"  # Tools that need to be actively selected by the agent
    POST_PROCESS = "post_process"  # Tools that automatically execute after final_answer


class ToolResult:
    """Tool execution result"""
    
    def __init__(self, status: str = None, result: Any = None, ext_data: Any = None):
        self.status = status
        self.result = result
        self.ext_data = ext_data

    @staticmethod
    def success(result, ext_data: Any = None):
        return ToolResult(status="success", result=result, ext_data=ext_data)

    @staticmethod
    def fail(result, ext_data: Any = None):
        return ToolResult(status="error", result=result, ext_data=ext_data)


class BaseTool:
    """Base class for all tools."""

    # Default decision stage is pre-process
    stage = ToolStage.PRE_PROCESS

    # Class attributes must be inherited
    name: str = "base_tool"
    description: str = "Base tool"
    params: dict = {}  # Store JSON Schema
    model: Optional[Any] = None  # LLM model instance, type depends on bot implementation

    @classmethod
    def get_json_schema(cls) -> dict:
        """Get the standard description of the tool"""
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": cls.params
        }

    def execute_tool(self, params: dict) -> ToolResult:
        try:
            return self.execute(params)
        except Exception as e:
            logger.error(e)

    def execute(self, params: dict) -> ToolResult:
        """Specific logic to be implemented by subclasses"""
        raise NotImplementedError

    @classmethod
    def _parse_schema(cls) -> dict:
        """Convert JSON Schema to Pydantic fields"""
        fields = {}
        for name, prop in cls.params["properties"].items():
            # Convert JSON Schema types to Python types
            type_map = {
                "string": str,
                "number": float,
                "integer": int,
                "boolean": bool,
                "array": list,
                "object": dict
            }
            fields[name] = (
                type_map[prop["type"]],
                prop.get("default", ...)
            )
        return fields

    def should_auto_execute(self, context) -> bool:
        """
        Determine if this tool should be automatically executed based on context.

        :param context: The agent context
        :return: True if the tool should be executed, False otherwise
        """
        # Only tools in post-process stage will be automatically executed
        return self.stage == ToolStage.POST_PROCESS

    def close(self):
        """
        Close any resources used by the tool.
        This method should be overridden by tools that need to clean up resources
        such as browser connections, file handles, etc.

        By default, this method does nothing.
        """
        pass
