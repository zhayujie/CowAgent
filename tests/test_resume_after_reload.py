"""A reply cut off or still running shows as such, and a page loaded mid-reply
can follow it from the last stored point without repeating or skipping."""

import threading
from types import SimpleNamespace

import pytest

from agent.memory import conversation_store
from agent.memory.conversation_store import ConversationStore
from channel.web import web_channel


WebChannel = dict(zip(
    web_channel.WebChannel.__code__.co_freevars,
    (cell.cell_contents for cell in web_channel.WebChannel.__closure__),
))["cls"]


def _tool_use(tool_id):
    return {"role": "assistant", "content": [
        {"type": "text", "text": f"checking {tool_id}"},
        {"type": "tool_use", "id": tool_id, "name": "browser", "input": {}},
    ]}


def _tool_result(tool_id):
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"},
    ]}


def _user(text):
    return {"role": "user", "content": text}


def _answer(text):
    return {"role": "assistant", "content": text}


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "history.db")


def _turns(store, **kwargs):
    return store.load_history_page("s1", **kwargs)["messages"]


def _open_run(store, run_id, messages):
    store.create_run(run_id, session_id="s1")
    store.append_messages("s1", messages, run_id=run_id)


# ------------------------------------------------------------------ history


def test_run_cut_off_by_restart_reads_interrupted(store):
    _open_run(store, "r1", [_user("q"), _tool_use("t1"), _tool_result("t1")])
    conversation_store._live_runs.discard("r1")  # the process that ran it is gone

    reply = _turns(store)[-1]

    assert reply["run_state"] == "interrupted"
    assert [step["type"] for step in reply["steps"]] == ["content", "tool"]


def test_run_in_progress_reads_running(store):
    _open_run(store, "r1", [_user("q"), _tool_use("t1"), _tool_result("t1")])

    assert _turns(store)[-1]["run_state"] == "running"


def test_run_with_nothing_stored_yet_still_gets_a_reply_turn(store):
    _open_run(store, "r1", [_user("q")])

    turns = _turns(store)

    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[-1]["run_state"] == "running"
    assert turns[-1]["steps"] == []


def test_failed_run_that_reached_its_answer_is_not_tagged(store):
    _open_run(store, "r1", [_user("q"), _tool_use("t1"), _tool_result("t1"), _answer("done")])
    store.finish_run("r1", status="failed", error="after the answer")

    reply = _turns(store)[-1]

    assert reply["content"] == "done"
    assert "run_state" not in reply


def test_completed_run_without_answer_adds_nothing(store):
    _open_run(store, "r1", [_user("q")])
    store.finish_run("r1", status="done")

    assert [t["role"] for t in _turns(store)] == ["user"]


def test_only_the_unfinished_turn_is_tagged(store):
    _open_run(store, "r0", [_user("old"), _answer("old answer")])
    store.finish_run("r0")
    _open_run(store, "r1", [_user("q"), _tool_use("t1"), _tool_result("t1")])
    store.finish_run("r1", status="failed")

    turns = _turns(store)

    assert [t.get("run_state") for t in turns if t["role"] == "assistant"] == [None, "interrupted"]


def test_max_seq_shows_the_reply_as_of_a_stored_point(store):
    _open_run(store, "r1", [
        _user("q"), _tool_use("t1"), _tool_result("t1"), _tool_use("t2"), _tool_result("t2"),
    ])

    reply = _turns(store, max_seq=2)[-1]

    assert [s.get("id") for s in reply["steps"] if s["type"] == "tool"] == ["t1"]
    assert reply["run_state"] == "running"


# ------------------------------------------------------------ restored context


def _restore(messages, **kwargs):
    from bridge.agent_initializer import AgentInitializer
    return AgentInitializer._restored_history(messages, **kwargs)


def _text_of(message):
    content = message["content"]
    return content if isinstance(content, str) else content[0]["text"]


def test_restored_cut_off_turn_keeps_its_steps():
    restored = _restore([
        _user("old"), _tool_use("t0"), _tool_result("t0"), _answer("old answer"),
        _user("q"), _tool_use("t1"), _tool_result("t1"), _tool_use("t2"), _tool_result("t2"),
    ], cut_off=True)

    assert [m["role"] for m in restored] == ["user", "assistant", "user", "assistant"] * 2 + [
        "user", "assistant",
    ]
    assert _text_of(restored[3]) == "old answer"
    assert restored[5] == _tool_use("t1")
    assert restored[-2] == _tool_result("t2")
    note = _text_of(restored[-1])
    assert note.startswith("_(Interrupted")
    assert note.count("- browser(") == 2
    assert "really ran" in note


def test_restored_cut_off_turn_drops_a_call_left_without_its_result():
    restored = _restore([
        _user("q"), _tool_use("t1"), _tool_result("t1"), _tool_use("t2"),
    ], cut_off=True)

    assert [m["role"] for m in restored] == ["user", "assistant", "user", "assistant"]
    assert restored[1] == _tool_use("t1")
    assert _text_of(restored[-1]).count("- browser(") == 1


def test_restored_cut_off_turn_with_unpaired_steps_falls_back_to_the_note():
    restored = _restore([
        _user("q"), _tool_use("t1"), _tool_result("other"),
    ], cut_off=True)

    assert [m["role"] for m in restored] == ["user", "assistant"]
    note = _text_of(restored[-1])
    assert note.startswith("_(Interrupted") and "- browser(" in note


def test_every_cut_off_turn_is_closed_with_a_note():
    restored = _restore([
        _user("a"), _tool_use("t1"), _tool_result("t1"),
        _user("b"), _tool_use("t2"), _tool_result("t2"),
    ], cut_off=True)

    assert [m["role"] for m in restored] == ["user", "assistant", "user", "assistant"] * 2
    assert restored[1] == _tool_use("t1")
    assert _text_of(restored[3]).startswith("_(Interrupted")
    assert restored[5] == _tool_use("t2")
    assert _text_of(restored[7]).startswith("_(Interrupted")


def test_an_old_cut_off_turn_flattens_to_its_note():
    from bridge.agent_initializer import _RESTORE_TOOL_TURNS

    finished = []
    for i in range(_RESTORE_TOOL_TURNS):
        finished += [_user(f"q{i}"), _answer(f"a{i}")]
    restored = _restore([_user("a"), _tool_use("t1"), _tool_result("t1")] + finished, cut_off=True)

    assert restored[0]["role"] == "user"
    assert _text_of(restored[1]).startswith("_(Interrupted") and "- browser(" in _text_of(restored[1])
    assert "tool_use" not in str(restored)


def test_restored_turn_cut_off_before_any_step_still_gets_a_reply():
    restored = _restore([_user("q")], cut_off=True)

    assert [m["role"] for m in restored] == ["user", "assistant"]
    assert _text_of(restored[-1]).startswith("_(Interrupted")


def test_finished_and_stopped_turns_get_no_note():
    restored = _restore([
        _user("a"), _tool_use("t1"), _tool_result("t1"), _answer("done"),
        _user("b"), _tool_use("t2"), _tool_result("t2"), _answer("_(Cancelled by user)_"),
    ], cut_off=True)

    assert "Interrupted" not in str(restored)


def test_turn_still_running_is_not_marked_by_default():
    restored = _restore([_user("q"), _tool_use("t1"), _tool_result("t1")])

    assert "Interrupted" not in str(restored)


# ------------------------------------------------------------ stored point


@pytest.fixture
def channel(store, monkeypatch):
    registry = SimpleNamespace(
        get=lambda agent_id=None: SimpleNamespace(id="primary", workspace="w"),
    )
    monkeypatch.setattr("agent.registry.get_agent_registry", lambda: registry)
    monkeypatch.setattr("agent.memory.get_conversation_store", lambda workspace=None: store)

    channel = SimpleNamespace(
        sse_streams={"req": web_channel.SSEStreamState()},
        _sse_streams_lock=threading.RLock(),
        request_to_session={"req": "s1"},
        request_to_agent={"req": "primary"},
        SSE_REPLAY_MAX_EVENTS=5000,
        SSE_REPLAY_MAX_BYTES=4 * 1024 * 1024,
    )
    channel._publish_sse_event = lambda rid, event: WebChannel._publish_sse_event(channel, rid, event)
    channel._mark_stored_point = lambda rid, advance_only: WebChannel._mark_stored_point(
        channel, rid, advance_only
    )
    channel.on_event = WebChannel._make_sse_callback(channel, "req")
    channel.resumable = lambda: WebChannel.resumable_stream(channel, "s1", "primary")
    return channel


def _delta(channel, text):
    channel.on_event({"type": "message_update", "data": {"delta": text}})


def test_stream_follows_on_from_the_last_stored_step(store, channel):
    _open_run(store, "r1", [_user("q")])
    channel.on_event({"type": "agent_start", "data": {}})
    assert channel.resumable() == {"request_id": "req", "stored_seq": 0, "after_seq": 0}

    _delta(channel, "checking t1")                              # event 1
    store.append_messages("s1", [_tool_use("t1"), _tool_result("t1")], run_id="r1")
    channel.on_event({"type": "turn_end", "data": {}})
    _delta(channel, "half of the next step")                    # event 2

    live = channel.resumable()
    assert live == {"request_id": "req", "stored_seq": 2, "after_seq": 1}
    # the page renders the stored step and replays only what came after it
    reply = _turns(store, max_seq=live["stored_seq"])[-1]
    assert [s["type"] for s in reply["steps"]] == ["content", "tool"]
    replay = [item for item, _ in channel.sse_streams["req"].events if item["seq"] > live["after_seq"]]
    assert [item["content"] for item in replay] == ["half of the next step"]


def test_step_that_was_not_stored_keeps_the_earlier_point(store, channel):
    _open_run(store, "r1", [_user("q")])
    channel.on_event({"type": "agent_start", "data": {}})
    _delta(channel, "lost step")
    channel.on_event({"type": "turn_end", "data": {}})  # nothing was written

    assert channel.resumable()["after_seq"] == 0


def test_stream_before_the_run_starts_is_followed_from_the_beginning(channel):
    assert channel.resumable() == {"request_id": "req", "stored_seq": None, "after_seq": 0}


def test_answered_stream_is_not_resumed(store, channel):
    _open_run(store, "r1", [_user("q")])
    channel.on_event({"type": "agent_start", "data": {}})
    channel._publish_sse_event("req", {"type": "done", "content": "answer"})

    assert channel.resumable() is None


def test_other_sessions_stream_is_not_resumed(channel):
    channel.request_to_session["req"] = "s2"

    assert channel.resumable() is None
