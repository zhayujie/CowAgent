"""An unknown ``action.type`` is a failed delivery, never a successful one.

``_run_scheduled_task`` returns "True if delivery succeeded", but a task whose
``action.type`` is none of the four known ones — hand-edited, downgraded or
half-written in ``tasks.json``, or written by another version — used to fall
through to ``ok = True`` with nothing ever sent. The caller trusted that: a
recurring task had its ``next_run_at`` advanced, so it silently never delivered
again, and a ``"once"`` task was deleted outright, its message gone for good.

An unknown type is a *retryable* failure. Reporting it as one keeps the task in
the store for the next tick, which is exactly what someone editing the store by
hand needs: fix the typo, and the message goes out.
"""

from datetime import datetime, timedelta

import pytest

from agent.memory import clear_conversation_store_cache, get_conversation_store
from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.task_store import TaskStore


@pytest.fixture
def one_agent(tmp_path):
    """Pin the registry to one Agent in tmp_path, so any run row the dispatcher
    opens lands in the temp workspace instead of the real install."""
    registry = AgentRegistry(
        [AgentProfile("default", "Default", str(tmp_path / "default"))],
        default_agent_id="default",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    try:
        yield registry
    finally:
        set_agent_registry(None)
        clear_conversation_store_cache()


def _task(action_type):
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


def test_unknown_action_type_is_reported_as_a_failed_delivery(monkeypatch, one_agent):
    from agent.tools.scheduler import integration

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)

    ok = integration._run_scheduled_task(
        _task("remind_me"), agent_bridge=object(), agent_id="default"
    )
    # Nothing was sent, so this cannot be a success the caller may act on.
    assert ok is False

    # It is still an *attempt*: the run is recorded, and as the failure it was.
    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert len(runs) == 1
    assert runs[0]["status"] == "error"


def test_unknown_action_type_keeps_a_one_time_task_in_the_store(
    monkeypatch, one_agent, tmp_path
):
    """The damage this caused end to end: a ``"once"`` task with an unknown
    action type was deleted the moment the tick "succeeded", so its message was
    never delivered and there was nothing left to retry."""
    from agent.tools.scheduler import integration

    store = TaskStore(str(tmp_path / "tasks.json"))
    now = datetime.now()
    # 10s overdue, inside the 10-minute catch-up window, so the tick really
    # runs the task: the only path that can delete it is the post-delivery one
    # under test (an expired one is dropped by _is_task_due instead).
    due_at = (now - timedelta(seconds=10)).isoformat()
    store.add_task(
        {
            "id": "once-1",
            "name": "one-shot digest",
            "enabled": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "next_run_at": due_at,
            "schedule": {"type": "once", "run_at": due_at},
            "action": {
                "type": "remind_me",
                "channel_type": "feishu",
                "receiver": "u-1",
                "content": "hi",
            },
        }
    )

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    executed = []

    def execute(task, trigger="scheduled"):
        executed.append(task["id"])
        return integration._run_scheduled_task(
            task, agent_bridge=object(), agent_id="default", trigger=trigger
        )

    SchedulerService(store, execute)._check_and_execute_tasks()

    # Guard against a vacuous pass: the tick really did dispatch the task.
    assert executed == ["once-1"]
    # A failed delivery is retried, not consumed: the task survives, still due.
    assert store.get_task("once-1") is not None
