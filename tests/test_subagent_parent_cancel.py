"""User Stop must reach an already running subagent's actual cancel event."""

import threading
from types import SimpleNamespace

from agent.subagent import SubagentSettings
from agent.subagent import runner
from agent.tools.subagent import SubagentTool


def test_user_stop_reaches_running_subagent(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "subagents").mkdir(parents=True)
    entered = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    parent_cancel = threading.Event()

    class Child:
        def run_stream(self, goal, clear_history, cancel_event, on_event):
            entered.set()
            while not release.wait(0.01):
                if cancel_event.is_set():
                    stopped.set()
                    return "stopped"
            return "fixture cleanup"

    monkeypatch.setattr(runner, "_build_child", lambda *args: Child())
    monkeypatch.setattr(runner, "_open_run", lambda *args: None)
    settings = SubagentSettings(timeout_seconds=2)
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: settings))
    tool = SubagentTool({"cwd": str(workspace)})
    tool.context = SimpleNamespace(workspace_dir=str(workspace))
    tool.cancel_event = parent_cancel
    result = []
    call = threading.Thread(target=lambda: result.append(tool.execute({"goal": "investigate"})))
    call.start()
    try:
        assert entered.wait(1), "child did not start"
        parent_cancel.set()
        assert stopped.wait(0.5), "user Stop never reached the spawned child"
        call.join(1)
        assert not call.is_alive(), "spawn call remained blocked after cancellation"
    finally:
        release.set()
        call.join(3)
        assert not call.is_alive(), "fixture leaked its spawn caller"


def test_already_cancelled_parent_never_starts_child(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "subagents").mkdir(parents=True)
    starts = []
    monkeypatch.setattr(runner, "_build_child", lambda *args: starts.append(True))
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: SubagentSettings()))
    tool = SubagentTool({"cwd": str(workspace)})
    tool.context = SimpleNamespace(workspace_dir=str(workspace))
    tool.cancel_event = threading.Event()
    tool.cancel_event.set()

    result = tool.execute({"goal": "investigate"})

    import json

    assert json.loads(result.result)["results"][0]["status"] == "cancelled"
    assert starts == []


def test_parent_stop_cancels_queued_children(monkeypatch):
    from agent.subagent import SubagentTask
    from agent.subagent.templates import GENERAL_PURPOSE

    entered = threading.Event()
    release = threading.Event()
    exited = threading.Event()
    parent_cancel = threading.Event()
    starts = []

    class Child:
        def run_stream(self, goal, clear_history, cancel_event, on_event):
            starts.append(goal)
            entered.set()
            try:
                while not release.wait(0.01):
                    if cancel_event.is_set():
                        return "stopped"
            finally:
                exited.set()
            return "fixture cleanup"

    monkeypatch.setattr(runner, "_build_child", lambda *args: Child())
    monkeypatch.setattr(runner, "_open_run", lambda *args: None)
    results = []
    call = threading.Thread(
        target=lambda: results.extend(
            runner.run_tasks(
                object(),
                [SubagentTask("first"), SubagentTask("queued")],
                {GENERAL_PURPOSE.name: GENERAL_PURPOSE},
                SubagentSettings(max_concurrent=1, timeout_seconds=2),
                cancel_event=parent_cancel,
            )
        )
    )
    call.start()
    try:
        assert entered.wait(1)
        parent_cancel.set()
        call.join(1)
        assert not call.is_alive()
        assert exited.wait(1)
        assert starts == ["first"]
        assert [r["status"] for r in results] == ["cancelled", "cancelled"]
    finally:
        release.set()
        call.join(3)
        assert exited.wait(1)


def test_timeout_keeps_parent_and_completed_sibling_uncancelled(monkeypatch):
    from agent.subagent import SubagentTask
    from agent.subagent.templates import GENERAL_PURPOSE

    release = threading.Event()
    exited = threading.Event()
    parent_cancel = threading.Event()
    seen_events = {}

    class Child:
        def run_stream(self, goal, clear_history, cancel_event, on_event):
            seen_events[goal] = cancel_event
            if goal == "sibling":
                return "done"
            try:
                release.wait(1)
                return "cleanup"
            finally:
                exited.set()

    monkeypatch.setattr(runner, "_build_child", lambda *args: Child())
    monkeypatch.setattr(runner, "_open_run", lambda *args: None)
    try:
        results = runner.run_tasks(
            object(),
            [SubagentTask("slow"), SubagentTask("sibling")],
            {GENERAL_PURPOSE.name: GENERAL_PURPOSE},
            SubagentSettings(timeout_seconds=0.1),
            cancel_event=parent_cancel,
        )
        assert [r["status"] for r in results] == ["timeout", "completed"]
        assert seen_events["slow"].is_set()
        assert not seen_events["sibling"].is_set()
        assert not parent_cancel.is_set()
    finally:
        release.set()
        assert exited.wait(1)


def test_normal_completion_preserves_parent_event(monkeypatch):
    from agent.subagent import SubagentTask
    from agent.subagent.templates import GENERAL_PURPOSE

    parent_cancel = threading.Event()

    class Child:
        def run_stream(self, goal, **kwargs):
            return "done"

    monkeypatch.setattr(runner, "_build_child", lambda *args: Child())
    monkeypatch.setattr(runner, "_open_run", lambda *args: None)
    results = runner.run_tasks(
        object(),
        [SubagentTask("normal")],
        {GENERAL_PURPOSE.name: GENERAL_PURPOSE},
        SubagentSettings(),
        cancel_event=parent_cancel,
    )
    assert results[0]["status"] == "completed"
    assert results[0]["summary"] == "done"
    assert not parent_cancel.is_set()


def test_stop_preserves_an_already_completed_sibling(monkeypatch):
    from agent.subagent import SubagentTask
    from agent.subagent.templates import GENERAL_PURPOSE

    sibling_done = threading.Event()
    release = threading.Event()
    slow_exited = threading.Event()
    parent_cancel = threading.Event()

    class Child:
        def run_stream(self, goal, clear_history, cancel_event, on_event):
            if goal == "sibling":
                return "sibling's completed work"
            try:
                while not release.wait(0.01):
                    if cancel_event.is_set():
                        return "stopped"
                return "fixture cleanup"
            finally:
                slow_exited.set()

    monkeypatch.setattr(runner, "_build_child", lambda *args: Child())
    monkeypatch.setattr(runner, "_open_run", lambda *args: None)
    real_pool = runner.ThreadPoolExecutor

    class ObservedPool(real_pool):
        def submit(self, function, *args, **kwargs):
            future = super().submit(function, *args, **kwargs)
            if args[3].goal == "sibling":
                future.add_done_callback(lambda _future: sibling_done.set())
            return future

    monkeypatch.setattr(runner, "ThreadPoolExecutor", ObservedPool)
    results = []
    call = threading.Thread(
        target=lambda: results.extend(
            runner.run_tasks(
                object(),
                [SubagentTask("slow"), SubagentTask("sibling")],
                {GENERAL_PURPOSE.name: GENERAL_PURPOSE},
                SubagentSettings(timeout_seconds=2),
                cancel_event=parent_cancel,
            )
        )
    )
    call.start()
    try:
        assert sibling_done.wait(1)
        parent_cancel.set()
        call.join(1)
        assert not call.is_alive()
        assert results[0]["status"] == "cancelled"
        assert results[1]["status"] == "completed"
        assert results[1]["summary"] == "sibling's completed work"
        assert slow_exited.wait(1)
    finally:
        release.set()
        call.join(3)
        assert slow_exited.wait(1)
