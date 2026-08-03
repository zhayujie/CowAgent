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
    progress_callback = None
    cancel_event = None
    # Workspace directory, injected per run. Declared here so a tool that
    # resolves relative paths cannot silently miss the injection.
    cwd: Optional[str] = None

    def is_cancelled(self) -> bool:
        """True once the user asked to stop the run.

        Long-running tools should poll this and abort early; the agent loop
        checkpoint right after the tool returns turns it into a clean cancel.
        """
        event = getattr(self, "cancel_event", None)
        return event is not None and event.is_set()

    def report_progress(self, message: str):
        callback = getattr(self, "progress_callback", None)
        if not callback:
            return
        try:
            callback(str(message))
        except Exception as e:
            logger.debug(f"[{self.name}] progress callback failed: {e}")

    @classmethod
    def get_json_schema(cls) -> dict:
        """Get the standard description of the tool"""
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": cls.params
        }

    def execute_tool(self, params: dict) -> ToolResult:
        """Run the tool, subject to the security policy.

        The gate lives here rather than in each tool because this is the one
        path every tool goes through, including MCP tools loaded at runtime
        that this repository never sees. A tool that forgets to check is the
        bug class issue #2998 is about, so the check is made impossible to
        forget by putting it above the subclass.

        A denial is returned as a normal failed ToolResult so the agent loop
        handles it like any other tool error: the model is told why, and can
        explain the refusal instead of crashing or silently retrying.
        """
        denial = self._security_check(params)
        if denial is not None:
            return denial
        try:
            result = self.execute(params)
        except Exception as e:
            logger.error(e)
            return None
        return self._screen_result(result)

    #: Tools whose output is content from outside the trust boundary, and so
    #: may carry instructions aimed at the model rather than at the user.
    UNTRUSTED_OUTPUT_TOOLS = frozenset(
        {"web_fetch", "web_search", "browser", "read", "search_files"}
    )

    def _screen_result(self, result):
        """Flag prompt-injection patterns in content the tool pulled in.

        Only annotates when something is actually detected, so ordinary results
        are returned byte-for-byte unchanged and the model's normal reading of
        them is untouched.
        """
        if result is None or not isinstance(getattr(result, "result", None), str):
            return result

        name = getattr(self, "name", "")
        is_mcp = bool(getattr(self, "is_mcp", False)) or name.startswith("mcp")
        if name not in self.UNTRUSTED_OUTPUT_TOOLS and not is_mcp:
            return result

        try:
            from config import conf

            if not conf().get("security_injection_detection", True):
                return result

            from agent.security import annotate_tool_result, audit, detect

            findings = detect(result.result)
            if findings:
                audit.record_injection(name, findings)
                result.result = annotate_tool_result(name, result.result, findings)
        except Exception as e:
            logger.debug(f"[{name}] Injection screening failed: {e}")
        return result

    def _security_check(self, params: dict) -> Optional[ToolResult]:
        """Return a failed ToolResult if policy forbids this call, else None.

        Never raises: a fault in the security layer must not become a way to
        break tool execution, and it must not become a way to bypass it either
        - hence the explicit fail-closed branch.
        """
        try:
            from agent.security import audit, evaluate_tool_call
        except Exception as e:  # pragma: no cover - security module unavailable
            logger.error(f"[{self.name}] Security subsystem unavailable: {e}")
            return None

        try:
            decision = evaluate_tool_call(
                tool_name=self.name,
                args=params if isinstance(params, dict) else {},
                cwd=getattr(self, "cwd", None),
            )
        except Exception as e:
            logger.error(f"[{self.name}] Security evaluation failed, denying call: {e}")
            return ToolResult.fail(
                "Error: the security policy could not be evaluated for this call, "
                "so it was not executed. Please report this to the user."
            )

        if decision.allowed:
            return None

        if decision.needs_confirmation:
            audit.record_confirmation(self.name, decision.category, **decision.details)
        else:
            audit.record_denial(self.name, decision.category, **decision.details)
        # The refusal carries a *structured* reason (not just prose) in
        # ext_data, so any caller that auto-retries, auto-degrades, or
        # auto-escalates can tell a missing-identity rejection (Case A) apart
        # from an ordinary unauthorized-user rejection (Case B) without parsing
        # the message. See the issue #2998 review: the return-to-caller layer
        # must differentiate, or for the machine the two cases are one case.
        return ToolResult.fail(
            decision.message,
            ext_data={
                "security_denial_category": decision.category,
                "security_identity_status": decision.details.get("identity_status", ""),
            },
        )

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
