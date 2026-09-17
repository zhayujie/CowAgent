"""A scheduled task's execution is recorded in the same global ``runs`` table
that native turns, delegations and subagents use — as ``task_source='scheduler'``
rows tagged with the owning ``agent_id`` — so task history JOINs cleanly with
everything else and needs no side-car store.
"""


import pytest

from agent.memory import (
    clear_conversation_store_cache,
    get_conversation_store,
)
from agent.registry import AgentProfile, AgentRegistry, get_agent_registry, set_agent_registry


@pytest.fixture
def one_agent(tmp_path):
    previous = get_agent_registry()
    registry = AgentRegistry(
        [AgentProfile("default", "Default", str(tmp_path / "default"))],
        default_agent_id="default",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    try:
        yield registry
    finally:
        set_agent_registry(previous)
        clear_conversation_store_cache()


def _task(action_type="send_message"):
    return {
        "id": "task-42",
        "name": "Daily digest",
        "action": {
            "type": action_type,
            "channel_type": "feishu",
            "receiver": "u-1",
            "notify_session_id": "sess-1",
            "content": "hi",
        },
    }


def test_successful_run_is_recorded_done(monkeypatch, one_agent):
    from agent.tools.scheduler import integration

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    monkeypatch.setattr(integration, "_execute_send_message", lambda *a, **k: True)

    ok = integration._run_scheduled_task(_task(), agent_bridge=object(), agent_id="default")
    assert ok is True

    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert len(runs) == 1
    row = runs[0]
    assert row["task_id"] == "task-42"
    assert row["task_source"] == "scheduler"
    assert row["status"] == "done"
    assert row["session_id"] == "sess-1"


def test_run_extras_capture_trigger_and_output_preview(monkeypatch, one_agent):
    """A recorded run keeps a light index of what fired it and what it sent:
    ``trigger`` (scheduled vs manual) and a short ``output_preview`` snippet."""
    from agent.tools.scheduler import integration

    def _deliver(task, agent_bridge, agent_id=None, output_sink=None):
        if output_sink is not None:
            output_sink["preview"] = "  hello world  "
        return True

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    monkeypatch.setattr(integration, "_execute_send_message", _deliver)

    ok = integration._run_scheduled_task(
        _task(), agent_bridge=object(), agent_id="default"
    )
    assert ok is True

    extras = get_conversation_store().list_runs(task_source="scheduler")[0]["extras"]
    assert extras["trigger"] == "scheduled"
    assert extras["task_name"] == "Daily digest"
    assert extras["action_type"] == "send_message"
    # Snippet is trimmed and length-capped, not a second copy of the body.
    assert extras["output_preview"] == "hello world"


def test_output_preview_is_truncated(monkeypatch, one_agent):
    from agent.tools.scheduler import integration

    long_body = "x" * (integration._OUTPUT_PREVIEW_LIMIT + 200)

    def _deliver(task, agent_bridge, agent_id=None, output_sink=None):
        if output_sink is not None:
            output_sink["preview"] = long_body
        return True

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    monkeypatch.setattr(integration, "_execute_send_message", _deliver)

    integration._run_scheduled_task(_task(), agent_bridge=object(), agent_id="default")

    extras = get_conversation_store().list_runs(task_source="scheduler")[0]["extras"]
    preview = extras["output_preview"]
    # Truncated to the limit plus a trailing ellipsis so a clipped preview never
    # reads as the whole message.
    assert preview.endswith("…")
    assert len(preview.rstrip("…")) <= integration._OUTPUT_PREVIEW_LIMIT
    assert len(preview) == integration._OUTPUT_PREVIEW_LIMIT + 1


def test_failed_delivery_is_recorded_error(monkeypatch, one_agent):
    from agent.tools.scheduler import integration

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    monkeypatch.setattr(integration, "_execute_send_message", lambda *a, **k: False)

    ok = integration._run_scheduled_task(_task(), agent_bridge=object(), agent_id="default")
    assert ok is False

    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert len(runs) == 1
    assert runs[0]["status"] == "error"


def test_not_ready_channel_records_no_run(monkeypatch, one_agent):
    """A deferral isn't an execution: it must not log a run every tick."""
    from agent.tools.scheduler import integration

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: False)

    ok = integration._run_scheduled_task(_task(), agent_bridge=object(), agent_id="default")
    assert ok is False

    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert runs == []


def test_exception_is_recorded_error_and_propagates(monkeypatch, one_agent):
    from agent.tools.scheduler import integration

    def _boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    monkeypatch.setattr(integration, "_execute_send_message", _boom)

    with pytest.raises(RuntimeError):
        integration._run_scheduled_task(_task(), agent_bridge=object(), agent_id="default")

    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert "kaboom" in runs[0]["error"]
