import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.steer import (
    SteerInbox,
    SteerRegistry,
    SteerResult,
    SteerStatus,
)
from bridge.context import Context, ContextType
from channel.chat_channel import ChatChannel


class _ScriptedExecutor(AgentStreamExecutor):
    def __init__(self, responses, inbox, steer_after_tool=None):
        super().__init__(
            agent=SimpleNamespace(),
            model=SimpleNamespace(model="test-model"),
            system_prompt="",
            tools=[],
            max_turns=8,
            messages=[],
            steer_inbox=inbox,
        )
        self.responses = list(responses)
        self.executed = []
        self.steer_after_tool = steer_after_tool

    def _is_thinking_enabled(self):
        return False

    def _trim_messages(self):
        return None

    def _validate_and_fix_messages(self):
        return None

    def _call_llm_stream(self, retry_on_empty=True):
        text, tool_calls, callback = self.responses.pop(0)
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
        if callback:
            callback()
        return text, tool_calls, "stop"

    def _execute_tool(self, tool_call):
        self.executed.append(tool_call["name"])
        if self.steer_after_tool == tool_call["name"]:
            self.steer_inbox.submit("use the new target")
        return {
            "status": "success",
            "result": f"finished {tool_call['name']}",
            "execution_time": 0.01,
        }


def _tool(name):
    return {"id": f"call-{name}", "name": name, "arguments": {}}


def _blocks(messages, block_type):
    return [
        block
        for message in messages
        for block in (message.get("content") or [])
        if isinstance(block, dict) and block.get("type") == block_type
    ]


def test_registry_accepts_only_one_active_run_and_preserves_order():
    registry = SteerRegistry()
    inbox = registry.register("research::session")

    assert registry.submit("other::session", "ignored").status == SteerStatus.INACTIVE
    assert registry.submit("research::session", "first").accepted
    assert registry.submit("research::session", "second").accepted
    assert inbox.drain() == ["first", "second"]

    second = registry.register("research::session")
    assert registry.submit("research::session", "ambiguous").status == SteerStatus.AMBIGUOUS
    registry.unregister("research::session", second)
    registry.unregister("research::session", inbox)
    assert registry.submit("research::session", "late").status == SteerStatus.INACTIVE


def test_inbox_bounds_and_atomic_close_gate():
    inbox = SteerInbox(max_pending=1, max_chars=5)
    assert inbox.submit("").status == SteerStatus.INVALID
    assert inbox.submit("123456").status == SteerStatus.INVALID
    assert inbox.submit("first").accepted
    assert inbox.submit("again").status == SteerStatus.FULL
    assert not inbox.close_if_empty()
    assert inbox.drain() == ["first"]
    assert inbox.close_if_empty()
    assert inbox.submit("late").status == SteerStatus.CLOSING


def test_steer_arriving_during_model_skips_all_proposed_tools():
    inbox = SteerInbox()
    executor = _ScriptedExecutor([
        ("old plan", [_tool("one"), _tool("two")], lambda: inbox.submit("change course")),
        ("new answer", [], None),
    ], inbox)

    assert executor.run_stream("start") == "new answer"
    assert executor.executed == []
    results = _blocks(executor.messages, "tool_result")
    assert {block["tool_use_id"] for block in results} == {"call-one", "call-two"}
    assert all(block.get("is_error") for block in results)
    assert "change course" in "\n".join(
        block["text"] for block in _blocks(executor.messages, "text")
    )


def test_steer_between_tools_keeps_completed_result_and_skips_remaining_tool():
    inbox = SteerInbox()
    executor = _ScriptedExecutor([
        ("", [_tool("one"), _tool("two")], None),
        ("redirected answer", [], None),
    ], inbox, steer_after_tool="one")

    assert executor.run_stream("start") == "redirected answer"
    assert executor.executed == ["one"]
    results = {block["tool_use_id"]: block for block in _blocks(executor.messages, "tool_result")}
    assert not results["call-one"].get("is_error", False)
    assert results["call-two"]["is_error"] is True


def _fake_agent_bridge(result):
    bridge = SimpleNamespace(
        steer_session=Mock(return_value=result),
        # Steering resolves the agent so it can scope the session key.
        route_context=Mock(return_value="default"),
        agent_router=SimpleNamespace(resolve=lambda **kwargs: "default"),
        scoped_session_key=lambda session_id, agent_id=None: session_id,
    )
    return bridge, SimpleNamespace(get_agent_bridge=lambda: bridge)


def test_chat_steer_command_bypasses_the_normal_queue(monkeypatch):
    bridge, factory = _fake_agent_bridge(SteerResult(SteerStatus.ACCEPTED))
    monkeypatch.setattr("bridge.bridge.Bridge", lambda: factory)
    channel = object.__new__(ChatChannel)
    channel.sessions = {}
    channel.lock = threading.Lock()
    channel._send_reply = Mock()
    context = Context(ContextType.TEXT, "/steer focus on tests", {
        "session_id": "session",
    })

    ChatChannel.produce(channel, context)

    assert channel.sessions == {}
    bridge.steer_session.assert_called_once_with("session", "focus on tests", "default")
    reply_text = channel._send_reply.call_args.args[1].content
    assert "redirect" in reply_text.lower() or "已引导" in reply_text


def test_ordinary_chat_message_keeps_using_the_session_queue(monkeypatch):
    _, factory = _fake_agent_bridge(SteerResult(SteerStatus.ACCEPTED))
    monkeypatch.setattr("bridge.bridge.Bridge", lambda: factory)
    monkeypatch.setattr("channel.chat_channel.conf", lambda: {
        "concurrency_in_session": 1,
    })
    channel = object.__new__(ChatChannel)
    channel.sessions = {}
    channel.lock = threading.Lock()
    context = Context(ContextType.TEXT, "ordinary message", {
        "session_id": "session",
    })

    ChatChannel.produce(channel, context)

    assert list(channel.sessions) == ["session"]
    assert channel.sessions["session"][0].get() is context


def test_web_steer_button_payload_is_handled_inline(monkeypatch):
    from channel.web import web_channel

    bridge, factory = _fake_agent_bridge(SteerResult(SteerStatus.ACCEPTED))
    monkeypatch.setattr("bridge.bridge.Bridge", lambda: factory)
    monkeypatch.setattr(web_channel.web, "data", lambda: json.dumps({
        "session_id": "session",
        "message": "focus on tests",
        "steer": True,
        "lang": "en",
    }).encode())
    raw_class = web_channel.WebChannel.__closure__[0].cell_contents
    instance = object.__new__(raw_class)

    response = json.loads(raw_class.post_message(instance))

    assert response == {
        "status": "success",
        "request_id": "",
        "stream": False,
        "steered": True,
        "inline_reply": "↪️ Active task redirected.",
    }
    bridge.steer_session.assert_called_once_with("session", "focus on tests", "default")


def test_web_steer_does_not_start_a_run_when_session_is_idle(monkeypatch):
    from channel.web import web_channel

    _, factory = _fake_agent_bridge(SteerResult(SteerStatus.INACTIVE))
    monkeypatch.setattr("bridge.bridge.Bridge", lambda: factory)
    monkeypatch.setattr(web_channel.web, "data", lambda: json.dumps({
        "session_id": "idle",
        "message": "/steer change course",
        "stream": True,
        "lang": "en",
    }).encode())
    raw_class = web_channel.WebChannel.__closure__[0].cell_contents
    instance = object.__new__(raw_class)

    response = json.loads(raw_class.post_message(instance))

    assert response["stream"] is False
    assert response["steered"] is False
    assert response["inline_reply"] == "No active task to steer."
