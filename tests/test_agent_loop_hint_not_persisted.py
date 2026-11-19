"""The loop-breaker hint is consumed by one model call, never persisted.

When a tool succeeds three times in a row with the same arguments, the loop
injects a hint telling the model to answer with what it already has. The hint
has to reach that model call, but it is not something the user said: a copy
left in the message list is stored as a user turn, rendered as a user bubble in
the chat history, and summarised into daily memory as if it were the user's
request. The tests below pin both halves: visible to the next call, gone from
the conversation afterwards.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor
from common.i18n import t as _t

LOOP_HINT = _t(
    "工具已成功执行并返回结果。请基于这些信息向用户做出回复，不要重复调用相同的工具。",
    "The tool already ran successfully and returned its result. Reply to the "
    "user from that result; do not call the same tool with the same arguments again.",
)
ANSWER = "done"


def _has_loop_hint(messages) -> bool:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text") == LOOP_HINT:
                return True
    return False


class _HintExecutor(AgentStreamExecutor):
    """The real agent loop, driven by a scripted model.

    Each scripted response is ``(text, tool_names)``. Every model call gets a
    snapshot of the message list as it stood at the call, which is how the
    tests tell "the hint was visible" from "the hint was left behind".
    """

    def __init__(self, script, max_turns=10):
        agent = SimpleNamespace(name="test-agent", messages=[], tools=[])
        super().__init__(
            agent=agent,
            model=SimpleNamespace(model="test-model"),
            system_prompt="",
            tools=[],
            max_turns=max_turns,
            messages=agent.messages,
        )
        self.script = list(script)
        self.call_snapshots = []

    def _is_thinking_enabled(self):
        return False

    def _trim_messages(self):
        # Trimming needs a real Agent for token accounting; the hint lifecycle
        # does not depend on it.
        return None

    def _validate_and_fix_messages(self):
        return None

    def _call_llm_stream(self, retry_on_empty=True):
        self.call_snapshots.append(list(self.messages))
        text, names = self.script.pop(0)
        calls = [
            {"id": f"call-{index}", "name": name, "arguments": {"path": "same.txt"}}
            for index, name in enumerate(names)
        ]
        content = [{"type": "text", "text": text}] if text else []
        content += [
            {"type": "tool_use", "id": call["id"], "name": call["name"], "input": dict(call["arguments"])}
            for call in calls
        ]
        self.messages.append({"role": "assistant", "content": content})
        return text, calls, "end_turn"

    def _execute_tool(self, tool_call):
        # Mirror the real success bookkeeping, which is what the loop hint
        # counts before it decides to fire.
        self._record_tool_result(tool_call["name"], tool_call["arguments"], True)
        return {"status": "success", "result": "ok", "execution_time": 0.01}


def _loop_script(turns=3):
    return [("", ["read"])] * turns + [(ANSWER, [])]


def test_hint_reaches_the_next_model_call_only():
    executor = _HintExecutor(script=_loop_script(3), max_turns=5)

    executor.run_stream("read the file")

    assert len(executor.call_snapshots) == 4
    assert not any(_has_loop_hint(snapshot) for snapshot in executor.call_snapshots[:3])
    assert _has_loop_hint(executor.call_snapshots[3]), "the hint was not visible to the model"
    assert not _has_loop_hint(executor.messages), "the hint was left in the conversation"


def test_hint_is_not_left_in_history_after_the_run():
    executor = _HintExecutor(script=_loop_script(3), max_turns=5)

    executor.run_stream("read the file")

    assert not _has_loop_hint(executor.messages)
    assert executor.messages[-1]["role"] == "assistant"


def test_hint_is_not_left_when_max_turns_is_hit():
    # The third tool turn injects the hint and exhausts the step budget in the
    # same turn, so the summary call is the one that consumes it.
    script = [("", ["read"])] * 3 + [("summary", [])]
    executor = _HintExecutor(script=script, max_turns=3)

    executor.run_stream("read the file")

    assert len(executor.call_snapshots) == 4
    assert _has_loop_hint(executor.call_snapshots[3])
    assert not _has_loop_hint(executor.messages)


def test_no_hint_when_loop_is_not_detected():
    executor = _HintExecutor(script=_loop_script(2), max_turns=5)

    executor.run_stream("read the file")

    assert not any(_has_loop_hint(snapshot) for snapshot in executor.call_snapshots)
    # user query + (tool_use + tool_result) x2 + final answer
    assert len(executor.messages) == 6


def test_repeated_hints_do_not_accumulate():
    # Five identical successes: a hint fires after the third, fourth and fifth
    # turn, and each one must be dropped by the call that consumed it.
    executor = _HintExecutor(script=_loop_script(5), max_turns=8)

    executor.run_stream("read the file")

    assert _has_loop_hint(executor.call_snapshots[3])
    assert _has_loop_hint(executor.call_snapshots[4])
    assert _has_loop_hint(executor.call_snapshots[5])
    assert sum(1 for snapshot in executor.call_snapshots if _has_loop_hint(snapshot)) == 3
    assert not _has_loop_hint(executor.messages)
