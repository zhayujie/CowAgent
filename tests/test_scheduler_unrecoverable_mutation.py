"""An unusable scheduler store must not turn a new reminder into data loss."""

import json

import pytest

from agent.tools.scheduler.scheduler_tool import SchedulerTool
from agent.tools.scheduler.task_store import TaskStore
from bridge.context import Context


@pytest.mark.parametrize("primary,backup", [
    ("{unfinished", "{also unfinished"),
    ('{"tasks": []}', "{also unfinished"),
    ('{"tasks": {"old": null}}', "{also unfinished"),
    (None, "{also unfinished"),
    ("{unfinished", None),
    ('{"tasks": []}', None),
    ('{"tasks": {"old": null}}', None),
])
def test_add_does_not_replace_an_unrecoverable_store(tmp_path, primary, backup):
    path = tmp_path / "tasks.json"
    backup_path = tmp_path / "tasks.json.bak"
    if primary is not None:
        path.write_text(primary, encoding="utf-8")
    if backup is not None:
        backup_path.write_text(backup, encoding="utf-8")
    before = {p: p.read_bytes() if p.exists() else None for p in (path, backup_path)}
    store = TaskStore(str(path))

    with pytest.raises(ValueError, match="unrecoverable task store"):
        store.add_task({"id": "new", "name": "must not replace old reminders"})

    assert {p: p.read_bytes() if p.exists() else None for p in before} == before
    # Preserve the read-only fallback relied on by the UI and old tests.
    assert store.load_tasks() == {}


def test_public_scheduler_reports_failed_creation_and_preserves_evidence(tmp_path):
    path = tmp_path / "tasks.json"
    original = b'{"tasks":{"old":{"id":"old","name":"unfinished reminder"'
    path.write_bytes(original)
    tool = SchedulerTool({"channel_type": "web"})
    tool.task_store = TaskStore(str(path))
    tool.current_context = Context(kwargs={"channel_type": "web", "receiver": "owned-local", "session_id": "owned-session"})

    result = tool.execute({"action": "create", "name": "owned reminder", "message": "local only", "schedule_type": "interval", "schedule_value": "300"})

    assert result.status == "error"
    assert "unrecoverable task store" in result.result
    assert path.read_bytes() == original
    assert not path.with_suffix(".json.bak").exists()


@pytest.mark.parametrize("initial", [None, {}])
def test_legitimate_new_or_empty_store_still_accepts_reminders(tmp_path, initial):
    path = tmp_path / "tasks.json"
    if initial is not None:
        path.write_text(json.dumps({"tasks": initial}), encoding="utf-8")
    store = TaskStore(str(path))
    assert store.add_task({"id": "first"}) is True
    assert store.get_task("first") == {"id": "first"}


@pytest.mark.parametrize("tasks", [{}, {"old": {"id": "old"}}])
def test_valid_backup_recovers_before_new_reminder(tmp_path, tasks):
    path = tmp_path / "tasks.json"
    path.write_text("{unfinished", encoding="utf-8")
    backup = path.with_suffix(".json.bak")
    backup.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    store = TaskStore(str(path))
    assert store.add_task({"id": "new"}) is True
    assert store.load_tasks() == {**tasks, "new": {"id": "new"}}


def test_explicit_save_keeps_the_existing_complete_replacement_api(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text("{unfinished", encoding="utf-8")
    backup = path.with_suffix(".json.bak")
    backup.write_text("{also unfinished", encoding="utf-8")
    store = TaskStore(str(path))
    store.save_tasks({})
    assert store.load_tasks() == {}
    assert json.loads(path.read_text(encoding="utf-8"))["tasks"] == {}
    assert store.add_task({"id": "new"}) is True
    assert store.get_task("new") == {"id": "new"}


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_other_mutations_already_fail_without_overwriting_corrupt_data(tmp_path, operation):
    path = tmp_path / "tasks.json"
    original = b'{"tasks":{"old":{"id":"old"'
    path.write_bytes(original)
    store = TaskStore(str(path))
    with pytest.raises(ValueError, match="not found"):
        if operation == "update":
            store.update_task("old", {"name": "new name"})
        else:
            store.delete_task("old")
    assert path.read_bytes() == original
    assert not path.with_suffix(".json.bak").exists()


def test_revalidation_keeps_tasks_restored_after_the_read_fallback(tmp_path, monkeypatch):
    path = tmp_path / "tasks.json"
    path.write_text("{unfinished", encoding="utf-8")
    store = TaskStore(str(path))
    real_load = store.load_tasks

    def load_then_repair_file():
        tasks = real_load()
        path.write_text(json.dumps({"tasks": {"restored": {"id": "restored"}}}), encoding="utf-8")
        return tasks

    monkeypatch.setattr(store, "load_tasks", load_then_repair_file)
    assert store.add_task({"id": "new"}) is True
    assert json.loads(path.read_text(encoding="utf-8"))["tasks"] == {
        "restored": {"id": "restored"}, "new": {"id": "new"},
    }
