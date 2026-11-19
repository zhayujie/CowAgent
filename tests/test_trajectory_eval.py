"""Deterministic trajectory evaluation scenarios for the Agent tool loop."""

from types import SimpleNamespace

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.base_tool import BaseTool, ToolResult

from tests.trajectory_eval import EvalCase, run_eval_case


class _LookupTool(BaseTool):
    name = "lookup"
    params = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def __init__(self, results):
        self.results = list(results)

    def execute(self, params):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _TestAgent:
    def effective_permission_mode(self):
        return "full-access"


class _ScriptedExecutor(AgentStreamExecutor):
    """Drive the real Agent loop with deterministic model responses."""

    def __init__(self, responses, tool, on_event):
        super().__init__(
            agent=_TestAgent(),
            model=SimpleNamespace(model="trajectory-test-model"),
            system_prompt="",
            tools=[tool] if tool else [],
            max_turns=8,
            on_event=on_event,
            messages=[],
        )
        self.responses = list(responses)

    def _is_thinking_enabled(self):
        return False

    def _trim_messages(self):
        return None

    def _validate_and_fix_messages(self):
        return None

    def _call_llm_stream(self, retry_on_empty=True):
        text, tool_calls = self.responses.pop(0)
        content = []
        if text:
            content.append({"type": "text", "text": text})
        content.extend({
            "type": "tool_use",
            "id": call["id"],
            "name": call["name"],
            "input": call.get("arguments", {}),
        } for call in tool_calls)
        self.messages.append({"role": "assistant", "content": content})
        return text, tool_calls, "stop"


def _call(index=1, query="status"):
    return {
        "id": "lookup-%s" % index,
        "name": "lookup",
        "arguments": {"query": query},
    }


def _run(case, responses, results=None):
    tool = _LookupTool(results or []) if results is not None else None

    def make_executor(recorder):
        return _ScriptedExecutor(responses, tool, recorder)

    return run_eval_case(case, make_executor)


def test_direct_answer_has_no_tool_trajectory():
    result = _run(
        EvalCase("direct_answer", "Say hello"),
        [("Hello", [])],
    )

    assert result.final_status == "done"
    assert result.turn_count == 1
    assert result.tool_call_count == 0
    assert result.selected_tools == []


def test_successful_tool_call_is_recorded():
    result = _run(
        EvalCase("successful_tool_call", "Look up status", ("lookup",)),
        [("", [_call()]), ("Status is ready", [])],
        [ToolResult.success("ready")],
    )

    assert result.final_status == "done"
    assert result.turn_count == 2
    assert result.tool_call_count == 1
    assert result.successful_tool_calls == 1
    assert result.failed_tool_calls == 0
    assert result.selected_tools == ["lookup"]


def test_failed_tool_call_is_distinguished_from_runtime_error():
    result = _run(
        EvalCase("failed_tool_call", "Look up status"),
        [("", [_call()]), ("I could not look it up", [])],
        [ToolResult.fail("service unavailable")],
    )

    assert result.final_status == "done"
    assert result.tool_call_count == 1
    assert result.successful_tool_calls == 0
    assert result.failed_tool_calls == 1
    assert result.error_count == 0


def test_tool_calls_record_arguments_and_status():
    result = _run(
        EvalCase("recorded_call", "Look up status", ("lookup",)),
        [("", [_call()]), ("Status is ready", [])],
        [ToolResult.success("ready")],
    )

    assert result.tool_calls == [{
        "tool_name": "lookup",
        "arguments": {"query": "status"},
        "status": "success",
    }]


def test_expected_tools_and_arguments_pass():
    result = _run(
        EvalCase(
            "expected_arguments",
            "Look up status",
            ("lookup",),
            expected_arguments={"lookup": {"query": "status"}},
        ),
        [("", [_call()]), ("Status is ready", [])],
        [ToolResult.success("ready")],
    )

    assert result.passed
    assert result.expectation_failures == []


def test_missing_expected_tool_fails_expectations():
    result = _run(
        EvalCase("missing_tool", "Look up status", ("lookup", "send_message")),
        [("", [_call()]), ("Status is ready", [])],
        [ToolResult.success("ready")],
    )

    assert not result.passed
    assert result.expectation_failures == [
        "expected tool 'send_message' was not called"
    ]


def test_wrong_arguments_fail_expectations():
    result = _run(
        EvalCase(
            "wrong_arguments",
            "Look up the weather",
            ("lookup",),
            expected_arguments={"lookup": {"query": "status"}},
        ),
        [("", [_call(query="weather")]), ("It is sunny", [])],
        [ToolResult.success("sunny")],
    )

    assert not result.passed
    assert len(result.expectation_failures) == 1
    assert "expected arguments" in result.expectation_failures[0]


def test_forbidden_tool_fails_expectations():
    result = _run(
        EvalCase(
            "forbidden_tool",
            "Answer directly",
            forbidden_tools=("lookup",),
        ),
        [("", [_call()]), ("Status is ready", [])],
        [ToolResult.success("ready")],
    )

    assert not result.passed
    assert result.expectation_failures == ["forbidden tool 'lookup' was called"]


def test_expected_status_mismatch_fails_expectations():
    result = _run(
        EvalCase("status_mismatch", "Say hello", expected_status="error"),
        [("Hello", [])],
    )

    assert not result.passed
    assert result.expectation_failures == ["expected status 'error', got 'done'"]


def test_eval_suite_of_recorded_cases_all_pass():
    """A small gate-style suite: every scripted case must meet its case."""
    suite = [
        (
            EvalCase("suite_direct", "Say hello"),
            [("Hello", [])],
            None,
        ),
        (
            EvalCase(
                "suite_lookup",
                "Look up status",
                ("lookup",),
                expected_arguments={"lookup": {"query": "status"}},
            ),
            [("", [_call()]), ("Status is ready", [])],
            [ToolResult.success("ready")],
        ),
        (
            EvalCase("suite_lookup_failure", "Look up status", ("lookup",)),
            [("", [_call()]), ("I could not look it up", [])],
            [ToolResult.fail("service unavailable")],
        ),
    ]

    for case, responses, results in suite:
        result = _run(case, responses, results)
        assert result.passed, (case.name, result.expectation_failures)


def test_recorder_handles_incomplete_tool_events():
    from tests.trajectory_eval import TrajectoryRecorder

    recorder = TrajectoryRecorder()
    recorder({"type": "turn_start", "timestamp": 1, "data": {"turn": 1}})
    recorder({
        "type": "tool_execution_start",
        "timestamp": 2,
        "data": {"tool_call_id": "unfinished", "tool_name": "lookup"},
    })

    result = recorder.result("incomplete")
    assert result.final_status == "incomplete"
    assert result.tool_call_count == 1
    assert result.failed_tool_calls == 0
