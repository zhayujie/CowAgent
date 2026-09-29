"""A run's messages are stored step by step, not only once it returns (#3179).

A long run that crashes or fails part-way must keep the steps it finished,
without storing any message twice or a tool call without its result.
"""

import threading
from types import SimpleNamespace

import pytest

import agent.protocol.agent as agent_mod
from agent.chat.service import ChatService
from agent.memory.conversation_store import ConversationStore
from agent.protocol.agent import Agent
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.step_writer import StepWriter, _closed_prefix
from bridge.agent_bridge import AgentBridge
from bridge.context import Context, ContextType


def _text(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _tool_use(tool_id):
    return {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": "read", "input": {}},
    ]}


def _tool_result(tool_id):
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "data"},
    ]}


def _label(message):
    block = message["content"][0]
    return block.get("text") or f"{block['type']}:{block.get('id') or block.get('tool_use_id')}"


class _Run:
    """The executor surface StepWriter reads: messages and run_start_index."""

    run_start_index = AgentStreamExecutor.run_start_index

    def __init__(self, history=(), query="q"):
        self.messages = list(history)
        self.run_user_message = _text("user", query)
        self.messages.append(self.run_user_message)


def _writer(**kwargs):
    chunks = []
    writer = StepWriter(lambda messages: chunks.append([_label(m) for m in messages]), **kwargs)
    return writer, chunks


# ---------------------------------------------------------------- StepWriter


def test_step_writes_only_this_run():
    run = _Run(history=[_text("user", "old q"), _text("assistant", "old a")])
    writer, chunks = _writer()
    writer.bind(run)
    run.messages += [_tool_use("t1"), _tool_result("t1")]

    writer.step()

    assert chunks == [["q", "tool_use:t1", "tool_result:t1"]]


def test_tool_use_waits_for_its_result():
    run = _Run()
    writer, chunks = _writer()
    writer.bind(run)
    run.messages += [_text("assistant", "looking"), _tool_use("t1")]

    writer.step()
    run.messages.append(_tool_result("t1"))
    writer.step()

    assert chunks == [["q", "looking"], ["tool_use:t1", "tool_result:t1"]]


def test_query_already_stored_is_skipped():
    run = _Run()
    writer, chunks = _writer(skip_query=True)
    writer.bind(run)
    run.messages.append(_text("assistant", "a"))

    writer.step()

    assert chunks == [["a"]]
    assert writer.started


def test_in_place_edits_neither_repeat_nor_skip():
    """The sanitizer drops and inserts messages between steps."""
    run = _Run()
    writer, chunks = _writer()
    writer.bind(run)
    run.messages += [_tool_use("t1"), _tool_result("t1")]
    writer.step()

    del run.messages[1]
    run.messages.insert(1, _text("assistant", "repaired"))
    run.messages.append(_text("assistant", "next"))
    writer.step()

    assert chunks == [["q", "tool_use:t1", "tool_result:t1"], ["repaired", "next"]]


def test_finish_writes_only_what_is_left():
    run = _Run()
    writer, chunks = _writer()
    writer.bind(run)
    run.messages += [_tool_use("t1"), _tool_result("t1")]
    writer.step()
    run.messages += [_text("assistant", "summary"), _tool_use("t2")]

    writer.finish(run.messages[run.run_start_index():])

    assert chunks[-1] == ["summary", "tool_use:t2"]


def test_lost_anchor_leaves_everything_to_finish():
    run = _Run()
    writer, chunks = _writer()
    writer.bind(run)
    run.messages.append(_text("assistant", "a"))
    batch = list(run.messages)
    run.run_user_message = None  # compaction replaced the query

    writer.step()
    assert chunks == []

    writer.finish(batch)
    assert chunks == [["q", "a"]]


def test_failed_write_is_retried_and_never_raises():
    calls = []

    def flaky(messages):
        calls.append(len(messages))
        if len(calls) == 1:
            raise OSError("database is locked")

    run = _Run()
    writer = StepWriter(flaky)
    writer.bind(run)
    run.messages.append(_text("assistant", "a"))

    writer.step()
    writer.step()

    assert calls == [2, 2]
    assert writer.started


def test_unbound_writer_is_a_no_op():
    writer, chunks = _writer()
    writer.step()
    assert chunks == []


# ---------------------------------------------------------------- real loop


class _Loop(AgentStreamExecutor):
    """The real agent loop, with the model and the tools scripted."""

    def __init__(self, responses, on_event, max_turns=8):
        super().__init__(
            agent=SimpleNamespace(), model=SimpleNamespace(model="test-model"),
            system_prompt="", tools=[], max_turns=max_turns, messages=[_text("user", "old q")],
            on_event=on_event,
        )
        self.responses = list(responses)

    def _is_thinking_enabled(self):
        return False

    def _trim_messages(self):
        return None

    def _validate_and_fix_messages(self):
        return None

    def _call_llm_stream(self, retry_on_empty=True):
        text, names = self.responses.pop(0)
        calls = [{"id": f"call-{n}", "name": n, "arguments": {}} for n in names]
        content = [{"type": "text", "text": text}] if text else []
        content += [
            {"type": "tool_use", "id": c["id"], "name": c["name"], "input": {}} for c in calls
        ]
        self.messages.append({"role": "assistant", "content": content})
        return text, calls, "stop"

    def _execute_tool(self, tool_call):
        return {"status": "success", "result": "ok", "execution_time": 0.01}


def _run_loop(responses, max_turns=8):
    chunks = []
    writer = StepWriter(lambda messages: chunks.append(messages))

    def on_event(event):
        if event["type"] == "turn_end":
            writer.step()

    executor = _Loop(responses, on_event, max_turns=max_turns)
    writer.bind(executor)
    executor.run_stream("new q")
    run = executor.messages[executor.run_start_index():]
    writer.finish(run)
    return run, chunks


@pytest.mark.parametrize("responses, max_turns", [
    ([("", ["one", "two"]), ("checking", ["three"]), ("done", [])], 8),
    # max steps reached: the summary lands after the last turn_end
    ([("", ["one"]), ("summary", [])], 1),
])
def test_real_loop_stores_every_message_once_in_order(responses, max_turns):
    run, chunks = _run_loop(responses, max_turns)

    written = [m for chunk in chunks for m in chunk]
    assert [id(m) for m in written] == [id(m) for m in run]
    assert len(chunks) > 1
    assert all(_closed_prefix(chunk) == len(chunk) for chunk in chunks)


# ---------------------------------------------------------------- Agent


def test_agent_hands_out_its_executor_before_running():
    seen = []

    class _Executor:
        def __init__(self, *, messages, **_):
            self.messages = list(messages)
            self.run_user_message = None

        def run_stream(self, user_message):
            seen.append("run")
            self.run_user_message = _text("user", user_message)
            self.messages.append(self.run_user_message)
            return "a"

        run_start_index = AgentStreamExecutor.run_start_index

    agent = Agent.__new__(Agent)
    agent.model = object()
    agent.tools = []
    agent.max_steps = 5
    agent.messages = []
    agent.messages_lock = threading.Lock()
    agent.get_full_system_prompt = lambda skill_filter=None: "sys"
    agent._execute_post_process_tools = lambda: None

    original = agent_mod.AgentStreamExecutor
    agent_mod.AgentStreamExecutor = _Executor
    try:
        agent.run_stream("hi", on_executor=lambda executor: seen.append(executor))
    finally:
        agent_mod.AgentStreamExecutor = original

    assert isinstance(seen[0], _Executor) and seen[1] == "run"


# ---------------------------------------------------------------- scripted runs


class _Script:
    """Replays steps like the real loop: messages, then turn_end."""

    def __init__(self, steps, tail=(), fail_at=None):
        self.steps = steps
        self.tail = list(tail)
        self.fail_at = fail_at

    def play(self, executor, query, on_event):
        executor.run_user_message = _text("user", query)
        executor.messages.append(executor.run_user_message)
        for i, step in enumerate(self.steps):
            executor.messages.extend(step)
            if i == self.fail_at:
                raise RuntimeError("provider down")
            on_event({"type": "turn_end", "data": {}})
        executor.messages.extend(self.tail)
        return "done"


_STEPS = [[_tool_use("t1"), _tool_result("t1")], [_text("assistant", "answer")]]
_FAILING = _Script([[_tool_use("t1"), _tool_result("t1")], [_tool_use("t2")]], fail_at=1)


# ---------------------------------------------------------------- ChatService


class _Registry:
    def register(self, *args, **kwargs):
        return threading.Event()

    def unregister(self, *args, **kwargs):
        pass


@pytest.fixture
def chat_run(monkeypatch):
    stored = []
    history = [_text("user", "old q"), _text("assistant", "old a")]
    agent = SimpleNamespace(
        model=SimpleNamespace(), tools=[], max_steps=5, messages=list(history),
        messages_lock=threading.Lock(), workspace_dir=None,
        get_full_system_prompt=lambda: "system", _execute_post_process_tools=lambda: None,
    )

    class _Bridge:
        agent_registry = SimpleNamespace(default_agent_id="primary")

        @staticmethod
        def _resolve_agent_id(agent_id=None):
            return agent_id or "primary"

        @staticmethod
        def _cancel_key(agent_id, token, default_agent_id):
            return token

        @staticmethod
        def get_agent(session_id=None, agent_id=None):
            return agent

    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: _Registry())
    monkeypatch.setattr("agent.protocol.get_steer_registry", lambda: _Registry())
    monkeypatch.setattr(
        ChatService, "_persist_messages",
        staticmethod(lambda sid, messages, *a, **k: stored.append([_label(m) for m in messages])),
    )

    def run(script):
        class _Executor:
            run_start_index = AgentStreamExecutor.run_start_index

            def __init__(self, *, messages, on_event, **_):
                self.messages = messages
                self.on_event = on_event
                self.run_user_message = None

            def run_stream(self, query):
                return script.play(self, query, self.on_event)

        monkeypatch.setattr("agent.protocol.agent_stream.AgentStreamExecutor", _Executor)
        service = ChatService(_Bridge())
        service._build_context = lambda *args, **kwargs: {}
        service._mark_run_active = lambda *args, **kwargs: None
        service._note_evolution_turn = lambda *args, **kwargs: None
        service.run("new q", "s1", lambda chunk: None)

    return SimpleNamespace(run=run, stored=stored)


def test_chat_service_stores_each_step_once(chat_run):
    chat_run.run(_Script(_STEPS, tail=[_text("assistant", "summary")]))

    assert chat_run.stored == [
        ["new q", "tool_use:t1", "tool_result:t1"],
        ["answer"],
        ["summary"],
    ]


def test_chat_service_failure_keeps_finished_steps(chat_run):
    with pytest.raises(RuntimeError):
        chat_run.run(_FAILING)

    # the failed step's unanswered tool call stays out of the store
    assert chat_run.stored == [["new q", "tool_use:t1", "tool_result:t1"]]


# ---------------------------------------------------------------- AgentBridge


class _ScriptedAgent:
    def __init__(self, script):
        self.script = script
        self.messages = [_text("user", "old q"), _text("assistant", "old a")]
        self.messages_lock = threading.RLock()
        self.tools = []
        self.model = SimpleNamespace()
        self.workspace_dir = None

    def run_stream(self, user_message, on_event=None, on_executor=None, **_):
        executor = SimpleNamespace(messages=list(self.messages), run_user_message=None)
        executor.run_start_index = lambda: AgentStreamExecutor.run_start_index(executor)
        if on_executor:
            on_executor(executor)
        response = self.script.play(executor, user_message, on_event)
        self._last_run_new_messages = executor.messages[executor.run_start_index():]
        self.messages = executor.messages
        return response


@pytest.fixture
def bridge_run(tmp_path, monkeypatch):
    from agent.registry import AgentRegistry

    store = ConversationStore(tmp_path / "conversations.db")
    registry = AgentRegistry.from_config({
        "default_agent_id": "primary",
        "agents": [{"id": "primary", "name": "Primary", "workspace": str(tmp_path / "p")}],
    })
    bridge = object.__new__(AgentBridge)
    bridge.agent_registry = registry
    bridge._agent_instances = {}
    bridge._agents_lock = threading.RLock()
    bridge.get_conversation_store = lambda agent_id=None: store
    bridge.route_context = lambda context: "primary"
    bridge._seed_team_members = lambda *args, **kwargs: None
    bridge._schedule_mcp_hot_reload = lambda agent: None
    monkeypatch.setattr("agent.evolution.trigger.note_user_turn", lambda *a, **k: None)
    monkeypatch.setattr("agent.evolution.trigger.mark_run_active", lambda *a, **k: None)

    def run(script, on_event=None):
        agent = _ScriptedAgent(script)
        bridge.get_agent = lambda **kwargs: agent
        context = Context(ContextType.TEXT, "new q", {"session_id": "s1", "channel_type": "web"})
        reply = bridge.agent_reply("new q", context=context, on_event=on_event)
        rows = store.load_messages("s1", max_turns=100, with_authors=True)
        return reply, rows

    run.store = store
    return run


def test_bridge_stores_reply_per_step_without_repeating_query(bridge_run):
    _, rows = bridge_run(_Script(_STEPS, tail=[_text("assistant", "summary")]))

    assert [_label(m) for m in rows] == [
        "new q", "tool_use:t1", "tool_result:t1", "answer", "summary",
    ]
    # replies keep their author stamp, the pre-stored query has none
    assert [m.get("agent_id") for m in rows][1:] == ["primary"] * 4


def test_bridge_failure_keeps_finished_steps(bridge_run):
    reply, rows = bridge_run(_FAILING)

    assert reply.type.name == "ERROR"
    assert [_label(m) for m in rows] == ["new q", "tool_use:t1", "tool_result:t1"]
    # the stored part of the failed turn is shown as cut off
    turns = bridge_run.store.load_history_page("s1")["messages"]
    assert turns[-1]["run_state"] == "interrupted"
    assert [step["type"] for step in turns[-1]["steps"]] == ["tool"]


def test_bridge_stores_step_before_announcing_turn_end(bridge_run):
    seen = []

    def on_event(event):
        if event.get("type") == "turn_end":
            seen.append(bridge_run.store.latest_seq("s1"))

    bridge_run(_Script(_STEPS), on_event=on_event)

    # query at 0; step one adds 1-2, step two adds 3
    assert seen == [2, 3]


def test_bridge_finished_turn_has_no_run_state(bridge_run):
    bridge_run(_Script(_STEPS))

    turns = bridge_run.store.load_history_page("s1")["messages"]
    assert turns[-1]["content"] == "answer"
    assert "run_state" not in turns[-1]
