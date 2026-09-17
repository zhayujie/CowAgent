from enum import Enum
from typing import Any, Optional
from common.log import logger


class ToolStage(Enum):
    """Enum representing tool decision stages"""
    PRE_PROCESS = "pre_process"  # Tools that need to be actively selected by the agent
    POST_PROCESS = "post_process"  # Tools that automatically execute after final_answer


class ToolResult:
    """Tool execution result

    ``result`` is what the model reads, so it is written for a model: JSON,
    exit codes, whatever parses cleanly. ``display`` is the same outcome
    written for a person, and clients render it instead when it is set. A tool
    whose result is already readable leaves it None and the two stay one thing.
    """

    def __init__(self, status: str = None, result: Any = None, ext_data: Any = None,
                 display: Optional[str] = None):
        self.status = status
        self.result = result
        self.ext_data = ext_data
        self.display = display

    @staticmethod
    def success(result, ext_data: Any = None, display: Optional[str] = None):
        return ToolResult(status="success", result=result, ext_data=ext_data, display=display)

    @staticmethod
    def fail(result, ext_data: Any = None, display: Optional[str] = None):
        return ToolResult(status="error", result=result, ext_data=ext_data, display=display)


def is_tool_available(tool) -> bool:
    """Availability of a tool that may not implement the check at all.

    Errs towards offering it: a check that breaks should cost the agent a log
    line, not a capability.
    """
    try:
        return bool(tool.is_available())
    except Exception as e:
        logger.debug(f"[{getattr(tool, 'name', '?')}] availability check failed: {e}")
        return True


def renders_own_cards(tool, arguments: dict) -> bool:
    """Whether a call reports itself. Errs towards the generic card, which is
    never wrong, only sometimes redundant."""
    if tool is None:
        return False
    try:
        return bool(tool.renders_own_cards(arguments))
    except Exception as e:
        logger.debug(f"[{getattr(tool, 'name', '?')}] card check failed: {e}")
        return False


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
    event_callback = None
    # Id of the call currently running, injected per call by the agent loop. A
    # tool that reports work of its own through `emit_event` needs it to say
    # which entry in the client's view that work belongs under.
    tool_call_id: Optional[str] = None
    # Workspace directory, injected per run. Declared here so a tool that
    # resolves relative paths cannot silently miss the injection.
    cwd: Optional[str] = None
    # Whether several calls to this tool in one turn may run at the same time.
    # Off by default: the agent loop runs tools in the order the model asked
    # for them, and most tools are written expecting exactly that. Turn it on
    # only for work that is independent by construction and slow enough that
    # queueing it is the dominant cost.
    parallel_safe: bool = False

    def renders_own_cards(self, arguments: dict) -> bool:
        """Whether this call reports itself, so the caller should stay quiet.

        A tool that runs several units of work at once can say which of them
        is still going, and the generic card wrapped around the whole call
        then shows the same thing a second time with every unit's arguments
        and every unit's output run together. Answering True for such a call
        leaves only the cards the tool emits itself. A failure that stops the
        tool before it emits anything still gets a card, otherwise it would
        vanish.
        """
        return False

    def is_available(self) -> bool:
        """Whether this tool should be offered to the model right now.

        Read once per turn, so a tool behind a setting the user can change
        mid-conversation answers for the setting as it stands rather than as
        it stood when the Agent was built. A tool that is always usable - the
        overwhelming majority - leaves this alone.
        """
        return True

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

    def emit_event(self, event_type: str, data: dict):
        """Report a unit of work running inside this call.

        One call is one entry in the client's view of the run. A tool that
        drives several independent pieces of work at once - and only such a
        tool - can announce each of them here, so the client can follow them
        separately instead of watching a single spinner stand in for all of
        them. Silent when nothing is listening.
        """
        callback = getattr(self, "event_callback", None)
        if not callback:
            return
        try:
            callback(event_type, data)
        except Exception as e:
            logger.debug(f"[{self.name}] event callback failed: {e}")

    def get_json_schema(self) -> dict:
        """The tool as the model sees it.

        Bound to the instance, not the class, so a tool whose name, wording or
        parameters depend on runtime state can override any of them in
        __init__ and have both this and the agent loop's direct read of
        `.description` agree.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.params
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
