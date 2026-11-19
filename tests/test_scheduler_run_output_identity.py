"""A scheduler run detail must recover only the message that run delivered."""

import sqlite3

import pytest

from agent.memory import clear_conversation_store_cache
from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from agent.tools.scheduler import integration
from bridge.agent_bridge import AgentBridge
from config import conf


class LocalDelivery:
    """No account or network: capture only the outbound delivery boundary."""

    def __init__(self):
        self.delivered = []

    def send(self, reply, context):
        self.delivered.append(reply.content)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import agent.evolution.trigger as evolution

    registry = AgentRegistry(
        [
            AgentProfile("default", "Default", str(tmp_path / "default")),
            AgentProfile("helper", "Helper", str(tmp_path / "helper")),
        ],
        "default",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    monkeypatch.setitem(conf(), "conversation_persistence", True)
    monkeypatch.setitem(conf(), "scheduler_inject_to_session", True)
    monkeypatch.setitem(conf(), "scheduler_inject_max_per_session", 3)
    # Suppress background jobs only; constructor, persistence, dispatch and
    # history recovery below are the real implementations.
    monkeypatch.setattr(integration, "init_scheduler", lambda *args: False)
    monkeypatch.setattr(evolution, "start_evolution_trigger", lambda *args: None)
    channel = LocalDelivery()
    monkeypatch.setattr(integration, "_resolve_delivery_channel", lambda *args: channel)
    monkeypatch.setattr("agent.memory.conversation_store.time.time", lambda: 1700000000)
    bridge = AgentBridge(object())
    try:
        yield bridge, channel
    finally:
        clear_conversation_store_cache()
        set_agent_registry(None)


def deliver(bridge, owner, task_id, content):
    task = {
        "id": task_id,
        "name": task_id,
        "action": {
            "type": "send_message",
            "channel_type": "web",
            "receiver": "chat",
            "content": content,
        },
    }
    assert integration._run_scheduled_task(task, bridge, owner)
    store = bridge.get_conversation_store(owner)
    runs = store.list_runs(task_id=task_id, agent_id=owner)
    assert len(runs) == 1
    return store, runs[0]["run_id"]


@pytest.mark.parametrize("owner", ["default", "helper"])
def test_same_second_deliveries_recover_their_own_full_body(runtime, owner):
    bridge, channel = runtime
    bodies = ["First report " + "A" * 1100, "Second report " + "B" * 1100]
    records = [
        deliver(bridge, owner, f"task-{i}", body) for i, body in enumerate(bodies)
    ]
    assert channel.delivered == bodies
    for (store, run_id), body in zip(records, bodies):
        detail = store.get_run_detail(run_id)
        assert detail["full_output"] == body
        assert len(detail["output_preview"]) == 1001
        with sqlite3.connect(store._db_path) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE run_id = ?", (run_id,)
                ).fetchone()[0]
                == 2
            )


@pytest.mark.parametrize("owner", ["default", "helper"])
def test_pruned_run_uses_its_preview_instead_of_another_delivery(runtime, owner):
    bridge, _ = runtime
    store, first = deliver(bridge, owner, "first", "First delivered report")
    _, second = deliver(bridge, owner, "second", "Second delivered report")
    assert store.prune_scheduled_messages("chat", keep_last_n=1) == 2
    detail = store.get_run_detail(first)
    assert detail["full_output"] is None
    assert detail["output_preview"] == "First delivered report"
    assert store.get_run_detail(second)["full_output"] == "Second delivered report"


def test_legacy_unassociated_run_never_borrows_current_message(runtime):
    bridge, _ = runtime
    store = bridge.get_conversation_store("helper")
    store.create_run(
        "legacy",
        agent_id="helper",
        session_id="chat",
        task_source="scheduler",
        extras={"output_preview": "Original historical preview"},
    )
    store.append_messages(
        "chat",
        [
            {"role": "user", "content": "[SCHEDULED] later task"},
            {"role": "assistant", "content": "Unrelated newer report"},
        ],
    )
    detail = store.get_run_detail("legacy")
    assert detail["full_output"] is None
    assert detail["output_preview"] == "Original historical preview"


def test_agent_scopes_and_normal_chat_do_not_replace_delivered_output(runtime):
    bridge, _ = runtime
    default_store, default_run = deliver(
        bridge, "default", "default-task", "Default report"
    )
    helper_store, helper_run = deliver(bridge, "helper", "helper-task", "Helper report")
    helper_store.append_messages(
        "chat",
        [
            {"role": "user", "content": "A normal follow-up"},
            {"role": "assistant", "content": "Normal chat answer"},
        ],
    )
    assert default_store.get_run_detail(default_run)["full_output"] == "Default report"
    assert helper_store.get_run_detail(helper_run)["full_output"] == "Helper report"


def test_legacy_remember_callback_still_receives_delivery(runtime):
    bridge, channel = runtime

    class LegacyBridge:
        def remember_scheduled_output(
            self, session_id, content, channel_type="", task_description=""
        ):
            bridge.remember_scheduled_output(
                session_id, content, channel_type, task_description
            )

    task = {
        "id": "legacy-callback",
        "name": "Legacy callback",
        "action": {
            "type": "send_message",
            "channel_type": "web",
            "receiver": "chat",
            "content": "Legacy delivered text",
        },
    }
    assert integration._run_scheduled_task(task, LegacyBridge(), "default")
    assert channel.delivered == ["Legacy delivered text"]
    store = bridge.get_conversation_store("default")
    assert (
        store.load_messages("chat")[-1]["content"][0]["text"] == "Legacy delivered text"
    )


@pytest.mark.parametrize("owner", ["default", "helper"])
def test_run_identity_stays_out_of_model_message_payload(runtime, owner):
    from agent.protocol import Agent

    bridge, _ = runtime
    cached = Agent("Local fixture", enable_skills=False, skip_context_files=True)
    bridge._agent_instances[(owner, "chat")] = cached
    store, run_id = deliver(bridge, owner, "memory-copy", "Visible scheduled text")
    assert len(cached.messages) == 2
    assert all(set(message) == {"role", "content"} for message in cached.messages)
    assert store.get_run_detail(run_id)["full_output"] == "Visible scheduled text"
