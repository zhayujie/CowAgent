# encoding:utf-8
"""A browser call that timed out must not run afterwards.

`_submit` gives the caller a TimeoutError so the model reports the action as
failed and may retry it. The queued call is still in the queue at that point;
running it anyway would perform the click / form submit that was just reported
as not happening, so a retry acts twice.
"""
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agent.tools.browser import browser_service


def _service(monkeypatch, budget=0):
    """A service whose worker is *this* thread, so no task runs on its own."""
    monkeypatch.setattr(browser_service, "_BROWSER_OP_BUDGET_S", budget)
    svc = browser_service.BrowserService.__new__(browser_service.BrowserService)
    svc._lock = threading.Lock()
    svc._alive = True
    svc._thread = threading.current_thread()  # makes _start_thread() a no-op
    svc._task_queue = queue.Queue()
    svc._needs_restart = False
    svc._playwright = None
    svc._idle_timeout = 0
    svc._idle_timer = None
    return svc


def test_a_timed_out_call_leaves_the_queued_task_marked_as_abandoned(monkeypatch):
    svc = _service(monkeypatch)
    performed = []

    with pytest.raises(TimeoutError):
        svc._submit(lambda: performed.append("clicked"))

    queued = svc._task_queue.get_nowait()
    assert queued[3].get("abandoned") is True, (
        "the worker cannot tell that nobody waits for this task any more"
    )
    assert performed == []


def test_the_worker_drops_an_abandoned_task_instead_of_running_it(monkeypatch):
    svc = _service(monkeypatch)
    performed = []
    slot = {"event": threading.Event(), "abandoned": True}

    svc._run_task((lambda: performed.append("clicked"), (), {}, slot))

    assert performed == [], "the click ran after the caller was told it failed"
    assert not slot["event"].is_set()


def test_a_waiting_caller_still_gets_its_task_run(monkeypatch):
    svc = _service(monkeypatch)
    slot = {"event": threading.Event()}
    svc._task_queue.put((lambda: "done", (), {}, slot))

    svc._run_task(svc._task_queue.get_nowait())

    assert slot["value"] == "done"
    assert slot["event"].is_set()


def test_a_lost_driver_still_fails_the_task(monkeypatch):
    svc = _service(monkeypatch)
    monkeypatch.setattr(svc, "_driver_connection_lost", lambda: True)
    slot = {"event": threading.Event()}
    svc._task_queue.put((lambda: "never", (), {}, slot))

    svc._run_task(svc._task_queue.get_nowait())

    assert isinstance(slot["error"], RuntimeError)
    assert slot["event"].is_set()
    assert svc._needs_restart is True
