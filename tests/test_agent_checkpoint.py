"""Tests for opt-in Agent run checkpoints."""

from types import SimpleNamespace

from agent.protocol import agent_stream
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.checkpoint import CheckpointManager


class RecordingCheckpointManager(CheckpointManager):
    saved_turns = []

    def save(self, session_id, messages, turn):
        type(self).saved_turns.append(turn)
        super().save(session_id, messages, turn)


class _CheckpointExecutor(AgentStreamExecutor):
    def __init__(self, responses):
        super().__init__(
            agent=SimpleNamespace(),
            model=SimpleNamespace(model="test-model"),
            system_prompt="",
            tools=[],
            max_turns=4,
            messages=[],
        )
        self.responses = list(responses)
        self.executed = []

    def _is_thinking_enabled(self):
        return False

    def _trim_messages(self):
        return None

    def _validate_and_fix_messages(self):
        return None

    def _call_llm_stream(self, retry_on_empty=True):
        text, tool_calls, _ = self.responses.pop(0)
        content = [{"type": "text", "text": text}] if text else []
        content.extend(
            {"type": "tool_use", "id": call["id"], "name": call["name"], "input": {}}
            for call in tool_calls
        )
        self.messages.append({"role": "assistant", "content": content})
        return text, tool_calls, "stop"

    def _execute_tool(self, tool_call):
        self.executed.append(tool_call["name"])
        return {"status": "success", "result": "ok", "execution_time": 0.01}


def _tool(name):
    return {"id": f"call-{name}", "name": name, "arguments": {}}


def _checkpoint_messages():
    return [
        {"role": "user", "content": [{"type": "text", "text": "start"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "call-one", "name": "one", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-one", "content": "ok"}]},
    ]


def test_checkpoint_roundtrip_and_corruption(tmp_path):
    manager = CheckpointManager(str(tmp_path))
    messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    manager.save("session/../id", messages, 2)

    assert manager.load("session/../id") == (messages, 2)
    assert manager.path_for("session/../id").parent == tmp_path

    manager.path_for("session/../id").write_text("{not json", encoding="utf-8")
    assert manager.load("session/../id") is None


def test_run_saves_completed_turns_and_clears_on_success(tmp_path, monkeypatch):
    RecordingCheckpointManager.saved_turns = []
    monkeypatch.setattr(agent_stream, "CheckpointManager", RecordingCheckpointManager)
    executor = _CheckpointExecutor([
        ("", [_tool("one")], None),
        ("done", [], None),
    ])

    assert executor.run_stream(
        "start", session_id="session-1", checkpoint_dir=str(tmp_path)
    ) == "done"
    assert executor.executed == ["one"]
    assert RecordingCheckpointManager.saved_turns == [0, 1]
    assert not list(tmp_path.glob("*.json"))


def test_resume_skips_completed_tool_turn(tmp_path):
    manager = CheckpointManager(str(tmp_path))
    messages = _checkpoint_messages()
    manager.save("session-1", messages, 1)
    executor = _CheckpointExecutor([("done", [], None)])

    assert executor.run_stream(
        "start", session_id="session-1", checkpoint_dir=str(tmp_path)
    ) == "done"
    assert executor.executed == []
    assert executor.messages == messages + [
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]}
    ]
    assert manager.load("session-1") is None


def test_invalid_checkpoint_falls_back_to_a_fresh_run(tmp_path):
    manager = CheckpointManager(str(tmp_path))
    manager.path_for("session-1").write_text("{not json", encoding="utf-8")
    executor = _CheckpointExecutor([
        ("", [_tool("one")], None),
        ("done", [], None),
    ])

    assert executor.run_stream(
        "start", session_id="session-1", checkpoint_dir=str(tmp_path)
    ) == "done"
    assert executor.executed == ["one"]
    assert manager.load("session-1") is None


def test_checkpoint_dir_requires_session_id(tmp_path):
    executor = _CheckpointExecutor([("done", [], None)])
    try:
        executor.run_stream("start", checkpoint_dir=str(tmp_path))
    except ValueError as error:
        assert "session_id" in str(error)
    else:
        raise AssertionError("expected ValueError for missing session_id")
