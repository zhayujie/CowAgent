"""A failed delivery must not re-run the scheduled task that produced it.

``_execute_agent_task`` / ``_execute_tool_call`` / ``_execute_skill_call``
returned False when ``channel.send`` raised, and False tells the scheduler loop
to keep ``next_run_at`` and retry on the next tick. Inside the ten-minute
catch-up window that meant every 30-second tick ran the whole task again —
a fresh agent run with its LLM calls and tool side effects — just to retry one
message. The send is now retried in place; once the task has run, the
occurrence is consumed and the run is recorded as failed.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent.memory import clear_conversation_store_cache, get_conversation_store
from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from agent.tools.scheduler import integration, scheduler_service
from agent.tools.scheduler.scheduler_service import SchedulerService
from agent.tools.scheduler.task_store import TaskStore


class Clock(datetime):
    current = datetime(2026, 11, 18, 9, 0, 5)

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


class _Bridge:
    def __init__(self):
        self.runs = 0

    def agent_reply(self, query, **kwargs):
        self.runs += 1
        return SimpleNamespace(content="daily report", type=None)


class _Channel:
    def __init__(self, failures):
        self.failures = failures
        self.attempts = 0
        self.delivered = []

    def send(self, reply, context):
        self.attempts += 1
        if self.failures is None or self.attempts <= self.failures:
            raise RuntimeError("IM API returned 502")
        self.delivered.append(reply.content)


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    registry = AgentRegistry(
        [AgentProfile("default", "Default", str(tmp_path / "default"))],
        default_agent_id="default",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    monkeypatch.setattr(scheduler_service, "datetime", Clock)
    Clock.current = datetime(2026, 11, 18, 9, 0, 5)
    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    monkeypatch.setattr(integration, "_remember_delivered_output", lambda *a, **k: None)
    monkeypatch.setattr(integration, "_DELIVERY_RETRY_DELAYS", (0, 0), raising=False)
    try:
        yield
    finally:
        set_agent_registry(None)
        clear_conversation_store_cache()


def _service(tmp_path, action, bridge):
    store = TaskStore(str(tmp_path / "tasks.json"))
    store.add_task({
        "id": "report",
        "name": "report",
        "enabled": True,
        "created_at": "2026-11-01T00:00:00",
        "next_run_at": "2026-11-18T09:00:00",
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "action": {"receiver": "user-1", "channel_type": "feishu", **action},
    })
    service = SchedulerService(
        store,
        lambda task, trigger="scheduled": integration._run_scheduled_task(
            task, bridge, "default", trigger
        ),
    )
    return store, service


def _tick(service, times):
    for _ in range(times):
        service._check_and_execute_tasks()
        Clock.current += timedelta(seconds=30)


def test_agent_task_is_not_rerun_when_its_delivery_keeps_failing(tmp_path, scheduler, monkeypatch):
    bridge, channel = _Bridge(), _Channel(failures=None)
    monkeypatch.setattr(integration, "_resolve_delivery_channel", lambda *a, **k: channel)
    store, service = _service(
        tmp_path, {"type": "agent_task", "task_description": "write the report"}, bridge
    )

    _tick(service, 5)

    assert bridge.runs == 1
    assert store.get_task("report")["next_run_at"].startswith("2026-11-19T09:00:00")
    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert "502" in runs[0]["error"]


def test_agent_task_delivery_survives_a_transient_send_failure(tmp_path, scheduler, monkeypatch):
    bridge, channel = _Bridge(), _Channel(failures=1)
    monkeypatch.setattr(integration, "_resolve_delivery_channel", lambda *a, **k: channel)
    store, service = _service(
        tmp_path, {"type": "agent_task", "task_description": "write the report"}, bridge
    )

    _tick(service, 3)

    assert bridge.runs == 1
    assert channel.delivered == ["daily report"]
    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert [run["status"] for run in runs] == ["done"]


def test_tool_call_is_not_rerun_when_its_delivery_keeps_failing(tmp_path, scheduler, monkeypatch):
    executions = []

    class _Tool:
        def execute(self, params):
            executions.append(params)
            return SimpleNamespace(result="posted to the webhook")

    from agent.tools import tool_manager

    monkeypatch.setattr(tool_manager.ToolManager, "create_tool", lambda self, name: _Tool())
    channel = _Channel(failures=None)
    monkeypatch.setattr(integration, "_resolve_delivery_channel", lambda *a, **k: channel)
    store, service = _service(
        tmp_path, {"type": "tool_call", "call_name": "webhook", "call_params": {"x": 1}}, _Bridge()
    )

    _tick(service, 5)

    assert len(executions) == 1
    assert store.get_task("report")["next_run_at"].startswith("2026-11-19T09:00:00")
