"""Concurrency regression tests for scheduler task persistence."""

import threading

from agent.tools.scheduler.task_store import TaskStore


def test_concurrent_adds_preserve_both_tasks(tmp_path):
    store_path = str(tmp_path / "tasks.json")
    first_store = TaskStore(store_path)
    second_store = TaskStore(store_path)
    first_load = first_store.load_tasks
    second_load = second_store.load_tasks
    first_save = first_store.save_tasks
    second_save = second_store.save_tasks
    first_loaded = threading.Event()
    second_loaded = threading.Event()
    second_saved = threading.Event()
    calls_lock = threading.Lock()
    load_calls = 0

    def coordinated_load(real_load):
        def load():
            nonlocal load_calls
            tasks = real_load()
            with calls_lock:
                load_calls += 1
                call_number = load_calls
            if call_number == 1:
                first_loaded.set()
                second_loaded.wait(timeout=0.5)
            elif call_number == 2:
                second_loaded.set()
            return tasks
        return load

    first_store.load_tasks = coordinated_load(first_load)
    second_store.load_tasks = coordinated_load(second_load)
    first_store.save_tasks = lambda tasks: (
        second_saved.wait(timeout=0.5), first_save(tasks)
    )[-1]

    def save_second(tasks):
        second_save(tasks)
        second_saved.set()

    second_store.save_tasks = save_second
    errors = []

    def add(task_id):
        try:
            current_store = first_store if task_id == "first" else second_store
            current_store.add_task({"id": task_id})
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=add, args=("first",))
    second = threading.Thread(target=add, args=("second",))
    first.start()
    assert first_loaded.wait(timeout=1)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert set(first_load()) == {"first", "second"}


def test_concurrent_updates_preserve_both_changes(tmp_path):
    store_path = str(tmp_path / "tasks.json")
    first_store = TaskStore(store_path)
    second_store = TaskStore(store_path)
    first_store.add_task({"id": "first", "name": "old"})
    first_store.add_task({"id": "second", "name": "old"})
    first_load = first_store.load_tasks
    second_load = second_store.load_tasks
    first_save = first_store.save_tasks
    second_save = second_store.save_tasks
    first_loaded = threading.Event()
    second_loaded = threading.Event()
    second_saved = threading.Event()
    calls_lock = threading.Lock()
    load_calls = 0

    def coordinated_load(real_load):
        def load():
            nonlocal load_calls
            tasks = real_load()
            with calls_lock:
                load_calls += 1
                call_number = load_calls
            if call_number == 1:
                first_loaded.set()
                second_loaded.wait(timeout=0.5)
            elif call_number == 2:
                second_loaded.set()
            return tasks
        return load

    first_store.load_tasks = coordinated_load(first_load)
    second_store.load_tasks = coordinated_load(second_load)
    first_store.save_tasks = lambda tasks: (
        second_saved.wait(timeout=0.5), first_save(tasks)
    )[-1]

    def save_second(tasks):
        second_save(tasks)
        second_saved.set()

    second_store.save_tasks = save_second
    first = threading.Thread(target=first_store.update_task, args=("first", {"name": "new"}))
    second = threading.Thread(target=second_store.update_task, args=("second", {"name": "new"}))
    first.start()
    assert first_loaded.wait(timeout=1)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    tasks = first_load()
    assert tasks["first"]["name"] == "new"
    assert tasks["second"]["name"] == "new"


def test_concurrent_deletes_preserve_both_removals(tmp_path):
    store_path = str(tmp_path / "tasks.json")
    first_store = TaskStore(store_path)
    second_store = TaskStore(store_path)
    first_store.add_task({"id": "first"})
    first_store.add_task({"id": "second"})
    first_load = first_store.load_tasks
    second_load = second_store.load_tasks
    first_save = first_store.save_tasks
    second_save = second_store.save_tasks
    first_loaded = threading.Event()
    second_loaded = threading.Event()
    second_saved = threading.Event()
    calls_lock = threading.Lock()
    load_calls = 0

    def coordinated_load(real_load):
        def load():
            nonlocal load_calls
            tasks = real_load()
            with calls_lock:
                load_calls += 1
                call_number = load_calls
            if call_number == 1:
                first_loaded.set()
                second_loaded.wait(timeout=0.5)
            elif call_number == 2:
                second_loaded.set()
            return tasks
        return load

    first_store.load_tasks = coordinated_load(first_load)
    second_store.load_tasks = coordinated_load(second_load)
    first_store.save_tasks = lambda tasks: (
        second_saved.wait(timeout=0.5), first_save(tasks)
    )[-1]

    def save_second(tasks):
        second_save(tasks)
        second_saved.set()

    second_store.save_tasks = save_second
    first = threading.Thread(target=first_store.delete_task, args=("first",))
    second = threading.Thread(target=second_store.delete_task, args=("second",))
    first.start()
    assert first_loaded.wait(timeout=1)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert first_load() == {}
