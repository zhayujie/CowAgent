from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional

from agent.protocol.task import Task, TaskStatus


class AgentActionType(Enum):
    """Enum representing different types of agent actions."""
    TOOL_USE = "tool_use"
    THINKING = "thinking"
    FINAL_ANSWER = "final_answer"


@dataclass
class ToolResult:
    """
    Represents the result of a tool use.
    
    Attributes:
        tool_name: Name of the tool used
        input_params: Parameters passed to the tool
        output: Output from the tool
        status: Status of the tool execution (success/error)
        error_message: Error message if the tool execution failed
        execution_time: Time taken to execute the tool
    """
    tool_name: str
    input_params: Dict[str, Any]
    output: Any
    status: str
    error_message: Optional[str] = None
    execution_time: float = 0.0


@dataclass
class AgentAction:
    """
    Represents an action taken by an agent.
    
    Attributes:
        id: Unique identifier for the action
        agent_id: ID of the agent that performed the action
        agent_name: Name of the agent that performed the action
        action_type: Type of action (tool use, thinking, final answer)
        content: Content of the action (thought content, final answer content)
        tool_result: Tool use details if action_type is TOOL_USE
        timestamp: When the action was performed
    """
    agent_id: str
    agent_name: str
    action_type: AgentActionType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    tool_result: Optional[ToolResult] = None
    thought: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentResult:
    """
    Represents the result of an agent's execution.

    Attributes:
        final_answer: The final answer provided by the agent
        step_count: Number of steps taken by the agent
        status: Status of the execution (success/error)
        error_message: Error message if execution failed
    """
    final_answer: str
    step_count: int
    status: str = "success"
    error_message: Optional[str] = None

    @classmethod
    def success(cls, final_answer: str, step_count: int) -> "AgentResult":
        """Create a successful result"""
        return cls(final_answer=final_answer, step_count=step_count)

    @classmethod
    def error(cls, error_message: str, step_count: int = 0) -> "AgentResult":
        """Create an error result"""
        return cls(
            final_answer=f"Error: {error_message}",
            step_count=step_count,
            status="error",
            error_message=error_message
        )

    @property
    def is_error(self) -> bool:
        """Check if the result represents an error"""
        return self.status == "error"