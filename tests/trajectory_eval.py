"""Small, deterministic helpers for evaluating Agent execution trajectories.

The evaluator consumes the existing AgentStreamExecutor event callback.  It is
intentionally test-only: it does not change runtime behavior or persist data.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple


@dataclass
class EvalCase:
    """A deterministic scenario and the outcome it should produce."""

    name: str
    user_message: str
    expected_tools: Tuple[str, ...] = ()
    expected_status: str = "done"
    forbidden_tools: Tuple[str, ...] = ()
    # Per-tool argument subsets: at least one call to the tool must carry
    # every key/value pair listed here.
    expected_arguments: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """Metrics collected from one Agent execution."""

    case_name: str
    final_status: str
    turn_count: int
    tool_call_count: int
    successful_tool_calls: int
    failed_tool_calls: int
    selected_tools: List[str]
    error_count: int
    duration_ms: float
    final_response: str = ""
    error: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    # One entry per tool call, in call order: tool_name, arguments, and the
    # end status when the call finished.
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    # Human-readable mismatches against the case's expectations. Only
    # populated when the result came from run_eval_case().
    expectation_failures: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Whether every expectation declared by the case held."""
        return not self.expectation_failures


class TrajectoryRecorder:
    """Collect Agent events and turn them into stable, testable metrics."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def __call__(self, event: Dict[str, Any]) -> None:
        if isinstance(event, dict):
            self.events.append(event)

    def result(
        self,
        case_name: str,
        final_response: str = "",
        error: str = "",
    ) -> EvaluationResult:
        starts = []
        ends = []
        runtime_errors = 0
        cancelled = False

        for event in self.events:
            event_type = event.get("type")
            data = event.get("data") or {}
            if event_type == "tool_execution_start":
                starts.append(data)
            elif event_type == "tool_execution_end":
                ends.append(data)
            elif event_type == "error":
                runtime_errors += 1
            elif event_type in ("agent_cancelled", "cancel"):
                cancelled = True

        if cancelled:
            status = "cancelled"
        elif error or runtime_errors:
            status = "error"
        elif any(event.get("type") == "agent_end" for event in self.events):
            status = "done"
        else:
            status = "incomplete"

        timestamps = [
            event.get("timestamp")
            for event in self.events
            if isinstance(event.get("timestamp"), (int, float))
        ]
        duration_ms = 0.0
        if len(timestamps) >= 2:
            duration_ms = max(0.0, (max(timestamps) - min(timestamps)) * 1000)

        selected_tools = []
        for data in starts:
            name = data.get("tool_name")
            if name and name not in selected_tools:
                selected_tools.append(name)

        successful = sum(data.get("status") == "success" for data in ends)
        failed = sum(data.get("status") != "success" for data in ends)

        ends_by_id = {
            data.get("tool_call_id"): data
            for data in ends
            if data.get("tool_call_id")
        }
        tool_calls = []
        for data in starts:
            call: Dict[str, Any] = {
                "tool_name": data.get("tool_name"),
                "arguments": data.get("arguments") or {},
            }
            end = ends_by_id.get(data.get("tool_call_id"))
            if end is not None:
                call["status"] = end.get("status")
            tool_calls.append(call)

        return EvaluationResult(
            case_name=case_name,
            final_status=status,
            turn_count=sum(event.get("type") == "turn_start" for event in self.events),
            tool_call_count=len({
                data.get("tool_call_id")
                for data in starts + ends
                if data.get("tool_call_id")
            }),
            successful_tool_calls=successful,
            failed_tool_calls=failed,
            selected_tools=selected_tools,
            error_count=runtime_errors,
            duration_ms=duration_ms,
            final_response=final_response or "",
            error=error,
            events=list(self.events),
            tool_calls=tool_calls,
        )


def _arguments_match(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    """Subset match: every expected key/value must be present in the call."""
    return all(actual.get(key) == value for key, value in expected.items())


def evaluate_expectations(case: EvalCase, result: EvaluationResult) -> List[str]:
    """Compare a finished trajectory against the case's declared expectations.

    Returns human-readable failure strings; an empty list means the run
    behaved exactly as the case declared (status, tool selection, and the
    arguments of at least one call per checked tool).
    """

    failures = []
    if result.final_status != case.expected_status:
        failures.append(
            "expected status %r, got %r" % (case.expected_status, result.final_status)
        )
    for tool in case.expected_tools:
        if tool not in result.selected_tools:
            failures.append("expected tool %r was not called" % tool)
    for tool in case.forbidden_tools:
        if tool in result.selected_tools:
            failures.append("forbidden tool %r was called" % tool)
    for tool, expected_args in case.expected_arguments.items():
        calls = [call for call in result.tool_calls if call.get("tool_name") == tool]
        if not calls:
            failures.append(
                "expected arguments for tool %r, but it was not called" % tool
            )
        elif not any(
            _arguments_match(call.get("arguments") or {}, expected_args)
            for call in calls
        ):
            failures.append(
                "no call to %r matched expected arguments %r" % (tool, expected_args)
            )
    return failures


def run_eval_case(case: EvalCase, executor_factory: Callable) -> EvaluationResult:
    """Run one case without letting a runtime exception hide its trajectory."""

    recorder = TrajectoryRecorder()
    executor = executor_factory(recorder)
    response = ""
    error = ""
    try:
        response = executor.run_stream(case.user_message)
    except Exception as exc:  # The result should make failed runs inspectable.
        error = str(exc)
    result = recorder.result(case.name, response, error)
    result.expectation_failures = evaluate_expectations(case, result)
    return result
