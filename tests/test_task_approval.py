# encoding:utf-8
"""Background tasks and approvals: store, rule matching, the gate, chat replies."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.task import store as st
from agent.task.approval import check, match_rule
from agent.task.commands import parse
from agent.task.settings import normalize_rules


@pytest.fixture
def store(tmp_path):
    instance = st.TaskStore(str(tmp_path / "tasks.db"))
    with patch.object(st, "_store", instance):
        yield instance


def _conf(enabled=True, rules=None):
    return {"task": {"enabled": enabled, "approval_rules": rules or []}}


def _agent(session_id="s1", context=None):
    return SimpleNamespace(_current_session_id=session_id, _current_agent_id="a1",
                           _current_context=context)


# --- store -------------------------------------------------------------------

def test_claim_moves_queued_to_running_once(store):
    task = store.create_task("t", "do it")
    assert task["status"] == st.QUEUED
    assert task["session_id"] == st.task_session_id(task["id"])
    claimed = store.claim_next(5)
    assert [t["id"] for t in claimed] == [task["id"]]
    assert claimed[0]["status"] == st.RUNNING and claimed[0]["run_count"] == 1
    assert store.claim_next(5) == []


def test_guarded_update_refuses_wrong_state(store):
    task = store.create_task("t", "p")
    assert not store.update_task(task["id"], expect_status=[st.RUNNING], status=st.DONE)
    assert store.update_task(task["id"], expect_status=[st.QUEUED], status=st.CANCELLED)


def test_requeue_interrupted_keeps_waiting(store):
    a = store.create_task("a", "p")
    b = store.create_task("b", "p")
    store.claim_next(2)
    store.update_task(b["id"], status=st.WAITING, wait_type=st.WAIT_APPROVAL)
    assert store.requeue_interrupted() == 1
    assert store.get_task(a["id"])["status"] == st.QUEUED
    assert store.get_task(b["id"])["status"] == st.WAITING


def test_pending_input_is_taken_once(store):
    task = store.create_task("t", "p")
    store.append_pending_input(task["id"], "one")
    store.append_pending_input(task["id"], "[Approval result] two", "Approved #2")
    assert store.take_pending_input(task["id"]) == ("one\n\n[Approval result] two", "one\n\nApproved #2")
    assert store.take_pending_input(task["id"]) == ("", "")


def test_older_database_gets_the_new_column(tmp_path):
    import sqlite3

    path = str(tmp_path / "tasks.db")
    conn = sqlite3.connect(path)
    conn.execute(st._SCHEMA[0])
    conn.commit()
    conn.close()
    st.TaskStore(path)
    st.TaskStore(path)
    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    conn.close()
    assert "pending_display" in columns


def test_same_pending_call_is_one_approval(store):
    first = store.create_approval(st.KIND_ACTION, session_id="s", tool_name="bash",
                                  tool_args={"command": "git push"})
    again = store.create_approval(st.KIND_ACTION, session_id="s", tool_name="bash",
                                  tool_args={"command": "git push"})
    assert first.get("is_new") and not again.get("is_new")
    assert first["id"] == again["id"]
    assert store.count_pending() == 1


def test_decision_settles_once(store):
    appr = store.create_approval(st.KIND_ACTION, session_id="s", tool_name="bash",
                                 tool_args={"command": "x"})
    assert store.decide_approval(appr["id"], st.APPROVED, via="web")
    assert not store.decide_approval(appr["id"], st.REJECTED, via="web")
    assert store.recent_decision("s", "bash", {"command": "x"})["status"] == st.APPROVED


# --- rules -------------------------------------------------------------------

def test_rules_normalized():
    rules = normalize_rules([{"tool": "bash", "action": "weird"}, {"match": "x"}, "junk"])
    assert len(rules) == 1
    assert rules[0]["action"] == "ask" and rules[0]["enabled"] and rules[0]["id"]


def test_hand_written_rules_keep_their_id_across_reads():
    raw = [{"tool": "bash", "match": "git push"}, {"tool": "bash", "match": "git push"}]
    first, second = normalize_rules(raw), normalize_rules(raw)
    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert first[0]["id"] != first[1]["id"]


def test_match_by_tool_and_pattern():
    rules = normalize_rules([
        {"tool": "bash", "match": r"git\s+push", "label": "push"},
        {"tool": "mcp_*,send", "label": "out"},
    ])
    assert match_rule(rules, "bash", {"command": "git push origin"})["label"] == "push"
    assert match_rule(rules, "bash", {"command": "ls"}) is None
    assert match_rule(rules, "mcp_mail_send", {})["label"] == "out"
    assert match_rule(rules, "read", {"path": "a"}) is None


def test_deny_wins_and_disabled_rules_skip():
    rules = normalize_rules([
        {"tool": "*", "label": "all"},
        {"tool": "bash", "match": "rm -rf", "action": "deny", "label": "no rm"},
        {"tool": "read", "enabled": False},
    ])
    assert match_rule(rules, "bash", {"command": "rm -rf /"})["action"] == "deny"
    assert match_rule(rules, "read", {})["label"] == "all"


def test_invalid_regex_matches_literally():
    rules = normalize_rules([{"tool": "bash", "match": "push("}])
    assert match_rule(rules, "bash", {"command": "push(x)"})
    assert not match_rule(rules, "bash", {"command": "pull"})


# --- gate --------------------------------------------------------------------

def test_gate_is_inert_when_disabled_or_unruled(store):
    with patch("config.conf", return_value=_conf(enabled=False, rules=[{"tool": "*"}])):
        assert check(_agent(), "bash", {"command": "x"}).action == "auto"
    with patch("config.conf", return_value=_conf(enabled=True)):
        assert check(_agent(), "bash", {"command": "x"}).action == "auto"
    assert store.count_pending() == 0


def test_gate_parks_then_replays_decision(store):
    rules = [{"tool": "bash", "match": "git push", "label": "Push code"}]
    with patch("config.conf", return_value=_conf(rules=rules)), \
            patch("agent.task.notify.notify_approval_pending") as notify:
        first = check(_agent(), "bash", {"command": "git push"})
        assert first.action == "ask" and "#%d" % first.approval["id"] in first.message
        assert notify.call_count == 1
        repeat = check(_agent(), "bash", {"command": "git push"})
        assert repeat.action == "ask" and repeat.approval["id"] == first.approval["id"]
        assert notify.call_count == 1

        store.decide_approval(first.approval["id"], st.REJECTED, note="not today")
        replay = check(_agent(), "bash", {"command": "git push"})
        assert replay.action == "replay" and "not today" in replay.message


def test_gate_deny_creates_no_approval(store):
    rules = [{"tool": "bash", "match": "rm -rf", "action": "deny", "label": "No rm"}]
    with patch("config.conf", return_value=_conf(rules=rules)):
        decision = check(_agent(), "bash", {"command": "rm -rf /tmp/x"})
    assert decision.action == "deny" and "No rm" in decision.message
    assert store.count_pending() == 0


# --- chat replies --------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("通过 5", ("approve", 5, "")),
    ("通过#5", ("approve", 5, "")),
    ("approve 12", ("approve", 12, "")),
    ("通过", ("approve", None, "")),
    ("驳回 5 改成明天发", ("reject", 5, "改成明天发")),
    ("reject 3", ("reject", 3, "")),
    ("驳回", ("reject", None, "")),
])
def test_parse_decisions(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize("text", ["通过了吗", "通过率是多少", "驳回原因是什么", "ok", "hello"])
def test_parse_ignores_chat(text):
    assert parse(text) is None


def test_reply_only_reaches_own_approvals(store):
    from agent.task.commands import try_handle

    mine = store.create_approval(st.KIND_ACTION, session_id="s", tool_name="bash",
                                 tool_args={"command": "a"},
                                 origin={"channel_type": "feishu", "receiver": "u1"})
    with patch("config.conf", return_value=_conf()), \
            patch("agent.task.approval.decide") as decide:
        assert try_handle("通过 %d" % mine["id"], "feishu", "u2") is None
        assert try_handle("通过 %d" % mine["id"], "feishu", "u1")
        decide.assert_called_once()
        assert try_handle("通过 %d" % mine["id"], "feishu", "u1") is not None
    with patch("config.conf", return_value=_conf(enabled=False)):
        assert try_handle("通过 %d" % mine["id"], "feishu", "u1") is None


# --- decisions -------------------------------------------------------------------

def test_reject_requeues_waiting_task_with_feedback(store):
    from agent.task.approval import DecisionError, decide

    task = store.create_task("t", "p")
    store.claim_next(1)
    store.update_task(task["id"], status=st.WAITING, wait_type=st.WAIT_APPROVAL)
    appr = store.create_approval(st.KIND_ACTION, task_id=task["id"], session_id=task["session_id"],
                                 tool_name="bash", tool_args={"command": "git push"})
    with patch("agent.task.runner.wake_runner") as wake:
        outcome = decide(appr["id"], "reject", note="not yet")
    assert outcome["approval"]["status"] == st.REJECTED and outcome["resume"] is None
    assert wake.call_count == 1
    task = store.get_task(task["id"])
    assert task["status"] == st.QUEUED and "not yet" in task["pending_input"]
    with pytest.raises(DecisionError):
        decide(appr["id"], "approve")


def test_review_accept_finishes_and_rework_requeues(store):
    from agent.task.approval import decide

    done = store.create_task("a", "p")
    redo = store.create_task("b", "p")
    for task in (done, redo):
        store.update_task(task["id"], status=st.WAITING, wait_type=st.WAIT_ACCEPT, result="draft")
    first = store.create_approval(st.KIND_ACCEPT, task_id=done["id"], session_id=done["session_id"])
    second = store.create_approval(st.KIND_ACCEPT, task_id=redo["id"], session_id=redo["session_id"])
    with patch("agent.task.runner.deliver_result") as deliver, \
            patch("agent.task.runner.wake_runner"):
        decide(first["id"], "approve")
        decide(second["id"], "reject", note="add sources")
    assert store.get_task(done["id"])["status"] == st.DONE
    deliver.assert_called_once()
    redo = store.get_task(redo["id"])
    assert redo["status"] == st.QUEUED and "add sources" in redo["pending_input"]


# --- tool and api ------------------------------------------------------------------

def test_task_tool_follows_the_master_switch():
    from agent.tools.task.task import TaskTool

    with patch("config.conf", return_value=_conf(enabled=False)):
        assert not TaskTool().is_available()
    with patch("config.conf", return_value=_conf(enabled=True)):
        assert TaskTool().is_available()


# --- scheduled runs ----------------------------------------------------------------

_SCHEDULE = {"id": "job1", "name": "daily", "action": {
    "type": "agent_task", "channel_type": "feishu", "receiver": "u1", "task_description": "report"}}


def test_scheduled_runs_skip_the_concurrency_limit(store):
    from agent.task.runner import TaskRunner

    for i in range(3):
        store.create_task(f"m{i}", "p")
    store.create_task("s", "p", source=st.SOURCE_SCHEDULE, schedule_id="job1")
    runner = TaskRunner()
    launched = []
    runner._launch = lambda task: launched.append(task["source"])
    runner._stop.is_set = iter([False, True]).__next__
    with patch("config.conf", return_value={"task": {"enabled": True, "max_concurrency": 1}}), \
            patch.object(runner._wake, "wait"):
        runner._active = {99: "busy"}
        runner._loop()
    assert launched == [st.SOURCE_SCHEDULE]


def test_a_firing_is_skipped_while_the_last_one_is_active(store):
    from agent.task import runner

    with patch("config.conf", return_value=_conf(enabled=True)), \
            patch("agent.task.runner.wake_runner"):
        assert runner.handoff_scheduled_task(_SCHEDULE, "a1", "scheduled")
        assert runner.handoff_scheduled_task(_SCHEDULE, "a1", "scheduled")
        assert store.count_tasks(schedule_id="job1") == 1
        first = store.list_tasks(limit=1)[0]
        store.update_task(first["id"], status=st.DONE)
        assert runner.handoff_scheduled_task(_SCHEDULE, "a1", "scheduled")
    assert store.count_tasks(schedule_id="job1") == 2


def test_scheduled_result_is_delivered_as_the_original_reply(store):
    from agent.task import runner
    from bridge.reply import Reply, ReplyType

    task = store.create_task("daily", "report", source=st.SOURCE_SCHEDULE, schedule_id="job1",
                             origin={"channel_type": "feishu", "receiver": "u1", "session_id": "u1"})
    store.update_task(task["id"], status=st.DONE, result="/tmp/chart.png")
    image = Reply(ReplyType.IMAGE, "/tmp/chart.png")
    with patch("agent.task.origin.send_to_origin", return_value=True) as send, \
            patch("agent.task.origin.send_text_to_origin") as send_text, \
            patch.object(runner, "_record_schedule_run", return_value="r1") as record, \
            patch.object(runner, "_schedule_of", return_value=_SCHEDULE), \
            patch.object(runner, "_get_bridge"), \
            patch("agent.tools.scheduler.integration._remember_delivered_output") as remember:
        runner.deliver_result(store.get_task(task["id"]), reply=image)
    assert send.call_args.args[1] is image
    send_text.assert_not_called()
    assert record.call_args.kwargs["status"] == "done"
    assert remember.call_args.args[3] == "/tmp/chart.png"


def _call(handler, method, body=None, params=None):
    import json

    from channel.web.api import tasks as api

    with patch.object(api, "_require_auth"), \
            patch.object(api.web, "header"), \
            patch.object(api.web, "data", return_value=json.dumps(body or {}).encode()), \
            patch.object(api.web, "input", side_effect=lambda **d: SimpleNamespace(**{**d, **(params or {})})):
        return json.loads(getattr(handler(), method)())


def test_api_create_refused_while_off_and_reported_when_on(store):
    from channel.web.api import tasks as api

    with patch("config.conf", return_value=_conf(enabled=False)):
        assert _call(api.TasksHandler, "POST", {"prompt": "x"})["status"] == "error"
        assert _call(api.TaskSummaryHandler, "GET")["enabled"] is False

    with patch("config.conf", return_value=_conf(enabled=True)), \
            patch("agent.task.runner.wake_runner"), \
            patch.object(api, "_default_agent_id", return_value="a1"):
        created = _call(api.TasksHandler, "POST", {"prompt": "write the weekly report\nmore"})
        assert created["status"] == "success"
        assert created["task"]["title"] == "write the weekly report"
        board = _call(api.TasksHandler, "GET", params={"agent_id": ""})
        assert [t["id"] for t in board["tasks"]] == [created["task"]["id"]]
        assert "pending_input" not in board["tasks"][0]

        store.create_approval(st.KIND_ACTION, session_id="s", tool_name="bash",
                              tool_args={"command": "git push"}, label="Push")
        summary = _call(api.TaskSummaryHandler, "GET", params={"since": "1"})
        assert summary["pending_approvals"] == 1
        assert [e["type"] for e in summary["events"]] == ["approval"]


def test_list_filters_by_status_and_source_and_pages(store):
    ids = []
    for i, source in enumerate((st.SOURCE_MANUAL, st.SOURCE_SCHEDULE, st.SOURCE_SCHEDULE, st.SOURCE_CHAT)):
        task = store.create_task(f"t{i}", "p", source=source)
        store.update_task(task["id"], status=st.DONE if i < 3 else st.FAILED)
        ids.append(task["id"])

    assert store.count_tasks(statuses=[st.DONE]) == 3
    assert store.count_tasks(statuses=[st.DONE], source=st.SOURCE_SCHEDULE) == 2
    first = store.list_tasks(statuses=[st.DONE], limit=2)
    rest = store.list_tasks(statuses=[st.DONE], limit=2, offset=2)
    assert [t["id"] for t in first + rest] == sorted(ids[:3], reverse=True)

    from channel.web.api import tasks as api

    with patch.object(api, "_default_agent_id", return_value="a1"):
        page = _call(api.TasksHandler, "GET", params={"agent_id": "", "status": "failed,cancelled", "source": ""})
    assert [t["id"] for t in page["tasks"]] == [ids[3]]
    assert page["total"] == 1
    assert page["counts"][st.DONE] == 3


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    import agent.evolution.trigger as evolution
    from agent.memory import clear_conversation_store_cache
    from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
    from agent.tools.scheduler import integration
    from bridge.agent_bridge import AgentBridge
    from config import conf

    set_agent_registry(AgentRegistry([AgentProfile("default", "Default", str(tmp_path / "ws"))], "default"))
    clear_conversation_store_cache()
    monkeypatch.setitem(conf(), "conversation_persistence", True)
    monkeypatch.setattr(integration, "init_scheduler", lambda *args: False)
    monkeypatch.setattr(evolution, "start_evolution_trigger", lambda *args: None)
    try:
        yield AgentBridge(object())
    finally:
        clear_conversation_store_cache()
        set_agent_registry(None)


def _texts(messages):
    return [b.get("text", "") for m in messages for b in (m.get("content") or []) if isinstance(b, dict)]


def test_chat_keeps_only_the_latest_task_results(bridge):
    for task_id in range(1, 8):
        bridge.remember_task_output("chat", task_id, f"t{task_id}", f"result {task_id}", channel_type="web")
    kept = [t for t in _texts(bridge.get_conversation_store().load_messages("chat")) if t.startswith("[TASK]")]
    assert kept == [f"[TASK] #{n} t{n}" for n in range(3, 8)]


def test_reply_depends_on_where_the_task_is(store):
    from agent.protocol.steer import SteerResult, SteerStatus
    from agent.task import runner

    running = store.create_task("r", "p")
    store.update_task(running["id"], status=st.RUNNING, run_count=1)
    queued = store.create_task("q", "p")
    done = store.create_task("d", "p", source=st.SOURCE_SCHEDULE, schedule_id="job1")
    store.update_task(done["id"], status=st.DONE, run_count=1, result="first")
    fake_bridge = SimpleNamespace(steer_session=lambda *a: SteerResult(SteerStatus.ACCEPTED))

    with patch.object(runner, "_bridge_ref", fake_bridge), patch("agent.task.runner.wake_runner"):
        assert runner.reply_to_task(running["id"], "use the new data") == "steer"
        assert runner.reply_to_task(queued["id"], "also the appendix") == "queued"
        assert runner.reply_to_task(done["id"], "add a chart") == "reopened"
        assert runner.reply_to_task(done["id"], "  ") is None

    assert store.get_task(queued["id"])["pending_input"] == "also the appendix"
    reopened = store.get_task(done["id"])
    assert reopened["status"] == st.QUEUED and reopened["origin"]["follow_up"]
    assert reopened["pending_display"] == "add a chart"


def test_reply_while_steering_is_closed_waits_for_the_next_round(store):
    from agent.protocol.steer import SteerResult, SteerStatus
    from agent.task import runner

    task = store.create_task("r", "p")
    store.update_task(task["id"], status=st.RUNNING, run_count=1)
    fake_bridge = SimpleNamespace(steer_session=lambda *a: SteerResult(SteerStatus.INACTIVE))
    with patch.object(runner, "_bridge_ref", fake_bridge):
        assert runner.reply_to_task(task["id"], "one more thing") == "queued"
    assert store.get_task(task["id"])["pending_input"] == "one more thing"


def test_reply_under_review_is_rework(store):
    from agent.task import runner

    task = store.create_task("t", "p", require_accept=True)
    store.update_task(task["id"], status=st.WAITING, wait_type=st.WAIT_ACCEPT, result="draft")
    store.create_approval(st.KIND_ACCEPT, task_id=task["id"], session_id=task["session_id"])
    with patch("agent.task.runner.wake_runner"):
        assert runner.reply_to_task(task["id"], "shorter please") == "rework"
    task = store.get_task(task["id"])
    assert task["status"] == st.QUEUED and "shorter please" in task["pending_input"]
    assert task["pending_display"].endswith("shorter please")


def test_follow_up_of_a_scheduled_run_stays_on_the_board(store):
    from agent.task import runner

    task = store.create_task("daily", "report", source=st.SOURCE_SCHEDULE, schedule_id="job1",
                             origin={"channel_type": "feishu", "receiver": "u1", "follow_up": True})
    store.update_task(task["id"], status=st.DONE, result="again")
    with patch.object(runner, "_deliver_scheduled") as deliver, \
            patch("agent.task.notify.notify_task_done"):
        runner.deliver_result(store.get_task(task["id"]))
    deliver.assert_not_called()


def test_round_display_shows_what_the_user_wrote(store):
    from agent.task.runner import _round_display

    first = {"id": 1, "prompt": "weekly report", "run_count": 1, "pending_display": ""}
    assert _round_display(first, "[Background task #1] ...") == "weekly report"
    later = {"id": 1, "prompt": "weekly report", "run_count": 2, "pending_display": "add a chart"}
    assert _round_display(later, "add a chart") == "add a chart"


def test_a_run_streams_to_the_console_and_always_closes(store):
    from agent.task import runner
    from bridge.reply import Reply, ReplyType

    web = SimpleNamespace(opened=[], closed=[])
    web.open_background_stream = lambda token, sid, aid: web.opened.append((token, sid, aid)) or "cb"
    web.close_background_stream = lambda token, content="": web.closed.append((token, content))
    seen = {}

    def reply(prompt, context=None, on_event=None):
        seen["on_event"] = on_event
        seen["display"] = context["display"]
        return Reply(ReplyType.TEXT, "all done")

    task = store.create_task("t", "weekly report")
    task["run_count"] = 1
    with patch("agent.task.origin.serving_web_channel", return_value=web), \
            patch.object(runner, "_bridge_ref", SimpleNamespace(agent_reply=reply)):
        runner._run_agent(task, "a1", "prompt", "tok")
    assert web.opened == [("tok", task["session_id"], "a1")]
    assert web.closed == [("tok", "all done")]
    assert seen == {"on_event": "cb", "display": "weekly report"}

    def boom(prompt, context=None, on_event=None):
        raise RuntimeError("model down")

    with patch("agent.task.origin.serving_web_channel", return_value=web), \
            patch.object(runner, "_bridge_ref", SimpleNamespace(agent_reply=boom)):
        with pytest.raises(RuntimeError):
            runner._run_agent(task, "a1", "prompt", "tok2")
    assert web.closed[-1] == ("tok2", "")


def test_output_landing_mid_run_survives_the_run():
    import threading

    import agent.protocol.agent as agent_mod
    from agent.protocol.agent import Agent

    landed = [
        {"role": "user", "content": [{"type": "text", "text": "[TASK] #1 report"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    ]

    class Executor:
        def __init__(self, *, agent, messages, **_):
            self.agent, self.messages = agent, list(messages)

        def run_start_index(self):
            return None

        def run_stream(self, text):
            self.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
            with self.agent.messages_lock:
                self.agent.messages.extend(landed)
            self.messages.append({"role": "assistant", "content": [{"type": "text", "text": "answer"}]})
            return "answer"

    agent = Agent.__new__(Agent)
    agent.model, agent.tools, agent.max_steps = object(), [], 10
    agent.messages = [{"role": "user", "content": [{"type": "text", "text": "q0"}]},
                      {"role": "assistant", "content": [{"type": "text", "text": "a0"}]}]
    agent.messages_lock = threading.Lock()
    agent.get_full_system_prompt = lambda skill_filter=None: "sys"
    agent._execute_post_process_tools = lambda: None
    with patch.object(agent_mod, "AgentStreamExecutor", Executor):
        agent.run_stream("hi")

    assert _texts(agent.messages) == ["q0", "a0", "hi", "answer", "[TASK] #1 report", "done"]
    assert _texts(agent._last_run_new_messages) == ["hi", "answer"]


def test_task_code_never_creates_the_web_channel():
    from common.singleton import singleton
    from agent.task.origin import serving_web_channel

    made = []

    @singleton
    class Thing:
        def __init__(self):
            made.append(1)

    assert Thing.peek() is None and not made
    assert Thing.peek() is None
    assert Thing() is Thing.peek()
    assert made == [1]

    with patch("channel.web.core.channel.WebChannel") as web_cls:
        web_cls.peek.return_value = None
        assert serving_web_channel() is None
        web_cls.assert_not_called()
