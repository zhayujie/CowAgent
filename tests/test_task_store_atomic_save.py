"""A failed save must not destroy the stored tasks, and the backup must be a
faithful copy of the file it duplicates.

``TaskStore.save_tasks`` used to open the store for writing immediately, so the
file was truncated before anything had been serialised: a task holding a value
json cannot encode made the call raise *after* the old contents were gone, and
``load_tasks()`` then swallowed the decode error and reported no tasks at all --
every scheduled task lost to one failed save. The ``.bak`` copy was taken
through the platform's default codec even though the store itself is written as
UTF-8, so on Windows it was decoded through the wrong one.
"""
import builtins
import json

import pytest

from agent.tools.scheduler.task_store import TaskStore


def _task(task_id):
    return {
        "id": task_id,
        "name": task_id,
        "schedule": {"type": "interval", "seconds": 60},
        "action": {"type": "send_message", "content": "提醒我开会", "receiver": "user-1"},
    }


def _write_store(path, tasks):
    path.write_text(
        json.dumps({"version": 1, "tasks": tasks}, ensure_ascii=False), encoding="utf-8"
    )


def test_a_failed_save_leaves_the_stored_tasks_on_disk(tmp_path):
    store_path = tmp_path / "tasks.json"
    _write_store(store_path, {"task-1": _task("task-1")})
    store = TaskStore(str(store_path))

    with pytest.raises(TypeError):
        store.save_tasks({"task-1": _task("task-1"), "bad": {"id": "bad", "when": {1, 2}}})

    assert set(store.load_tasks()) == {"task-1"}


def test_a_failed_save_leaves_the_backup_usable(tmp_path):
    store_path = tmp_path / "tasks.json"
    _write_store(store_path, {"task-1": _task("task-1")})
    store = TaskStore(str(store_path))
    before = store_path.read_text(encoding="utf-8")

    with pytest.raises(TypeError):
        store.save_tasks({"bad": {"id": "bad", "when": {1, 2}}})

    backup_path = tmp_path / "tasks.json.bak"
    json.loads(backup_path.read_text(encoding="utf-8"))  # still parseable
    assert backup_path.read_text(encoding="utf-8") == before


def test_the_save_path_never_relies_on_the_platform_codec(tmp_path, monkeypatch):
    """Pin the encoding the save path asks for.

    The failure this guards is the platform default codec, which cannot be
    changed from inside a running process (`open()` reads it through C, not
    through ``locale.getpreferredencoding``), so the contract is asserted
    where it is observable: every text-mode open the save performs.
    """
    store_path = tmp_path / "tasks.json"
    _write_store(store_path, {"task-1": _task("task-1")})
    store = TaskStore(str(store_path))

    opened = []
    real_open = builtins.open

    def spy(file, mode="r", *args, **kwargs):
        opened.append((str(file), mode, kwargs.get("encoding")))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    try:
        store.save_tasks({"task-1": _task("task-1")})
    finally:
        monkeypatch.undo()

    text_opens = [entry for entry in opened if "b" not in entry[1]]
    assert text_opens, "expected the save path to open files in text mode"
    assert {encoding for _, _, encoding in text_opens} == {"utf-8"}


def test_a_successful_save_replaces_the_store_and_keeps_a_backup(tmp_path):
    store_path = tmp_path / "tasks.json"
    _write_store(store_path, {"task-1": _task("task-1")})
    store = TaskStore(str(store_path))

    store.save_tasks({"task-1": _task("task-1"), "task-2": _task("task-2")})

    assert set(store.load_tasks()) == {"task-1", "task-2"}
    backup = json.loads((tmp_path / "tasks.json.bak").read_text(encoding="utf-8"))
    assert set(backup["tasks"]) == {"task-1"}
    assert backup["tasks"]["task-1"]["action"]["content"] == "提醒我开会"


def test_a_successful_save_leaves_no_temporary_file_behind(tmp_path):
    store_path = tmp_path / "tasks.json"
    store = TaskStore(str(store_path))

    store.save_tasks({"task-1": _task("task-1")})

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["tasks.json"]
