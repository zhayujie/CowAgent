# encoding:utf-8
"""A scheduled skill run must look scheduled to the agent bridge.

`agent_bridge` keys four behaviours off ``context["is_scheduled_task"]``: it
strips the scheduler tool so a scheduled run cannot create another task, it
allows an empty answer to stay empty, and it keeps the run out of the idle
self-evolution scan. `_execute_agent_task` sets it; `_execute_skill_call` is the
other way a task reaches `agent_reply` and did not.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.scheduler import integration
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType


class _Bridge:
    """Records the context each scheduled run is started with."""

    def __init__(self, content="done"):
        self.contexts = []
        self.content = content

    def agent_reply(self, query, context=None, on_event=None, clear_history=False):
        self.contexts.append(context)
        return Reply(ReplyType.TEXT, self.content)


def _task(**action):
    base = {"type": "skill_call", "call_name": "weather", "receiver": "u1",
            "channel_type": "web"}
    base.update(action)
    return {"id": "t1", "name": "t1", "action": base}


def _isolate(monkeypatch, delivered=None):
    """Cut the delivery side out: only the agent call is under test."""
    channel = SimpleNamespace(request_to_session={})
    monkeypatch.setattr(integration, "_resolve_delivery_channel", lambda *a, **k: channel)
    sent = delivered if delivered is not None else []

    def deliver(ch, reply, context, task, output_sink=None):
        sent.append(reply)
        return True

    monkeypatch.setattr(integration, "_deliver_result", deliver)
    monkeypatch.setattr(integration, "_remember_delivered_output", lambda *a, **k: None)
    return sent


def test_a_skill_call_runs_as_a_scheduled_task(monkeypatch):
    sent = _isolate(monkeypatch)
    bridge = _Bridge()

    assert integration._execute_skill_call(_task(), bridge) is True

    context = bridge.contexts[0]
    assert context.type == ContextType.TEXT
    assert context.get("is_scheduled_task") is True, (
        "the bridge cannot tell this is a scheduled run, so the scheduler tool stays"
    )
    assert len(sent) == 1


def test_a_scheduled_run_is_marked_before_the_agent_is_called(monkeypatch):
    """The flag has to be on the context the bridge sees, not added afterwards."""
    seen = {}
    monkeypatch.setattr(integration, "_resolve_delivery_channel",
                        lambda *a, **k: SimpleNamespace(request_to_session={}))
    monkeypatch.setattr(integration, "_deliver_result", lambda *a, **k: True)
    monkeypatch.setattr(integration, "_remember_delivered_output", lambda *a, **k: None)

    class _Peek(_Bridge):
        def agent_reply(self, query, context=None, on_event=None, clear_history=False):
            seen["is_scheduled_task"] = context.get("is_scheduled_task")
            return Reply(ReplyType.TEXT, "done")

    integration._execute_skill_call(_task(), _Peek())

    assert seen.get("is_scheduled_task") is True


def test_an_empty_skill_result_is_still_delivered_nowhere(monkeypatch):
    """The control: marking the run scheduled must not change what is sent."""
    sent = _isolate(monkeypatch)
    bridge = _Bridge(content="")

    assert integration._execute_skill_call(_task(), bridge) is True
    assert sent == []
