"""
Task storage management for scheduler
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional
from common.utils import expand_path


_store_locks = {}
_store_locks_guard = threading.Lock()


def _lock_for_path(store_path: str):
    normalized_path = os.path.normcase(os.path.realpath(store_path))
    with _store_locks_guard:
        return _store_locks.setdefault(normalized_path, threading.RLock())


class _DescStr:
    """Sort a string descending inside an otherwise-ascending sort key tuple.

    Lets ``sort_key`` mix an ascending rank (enabled-first) with a descending
    field (newest ``created_at`` on top) in one ``sort`` call, without a second
    pass or reversing the whole list.
    """

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value or ""

    def __lt__(self, other: "_DescStr") -> bool:
        # Reversed comparison => larger (later) strings sort first.
        return self.value > other.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _DescStr) and self.value == other.value


class TaskStore:
    """
    Manages persistent storage of scheduled tasks
    """

    def __init__(self, store_path: str = None):
        """
        Initialize task store

        Args:
            store_path: Path to tasks.json file. Defaults to ~/cow/scheduler/tasks.json
        """
        if store_path is None:
            # Default to ~/cow/scheduler/tasks.json
            home = expand_path("~")
            store_path = os.path.join(home, "cow", "scheduler", "tasks.json")

        self.store_path = store_path
        self.lock = _lock_for_path(store_path)
        self._ensure_store_dir()

    def _ensure_store_dir(self):
        """Ensure the storage directory exists"""
        store_dir = os.path.dirname(self.store_path)
        os.makedirs(store_dir, exist_ok=True)

    def load_tasks(self) -> Dict[str, dict]:
        """
        Load all tasks from storage

        Returns:
            Dictionary of task_id -> task_data
        """
        with self.lock:
            if not os.path.exists(self.store_path):
                return {}

            try:
                with open(self.store_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("tasks", {})
            except Exception as e:
                print(f"Error loading tasks: {e}")
                return {}

    def save_tasks(self, tasks: Dict[str, dict]):
        """
        Save all tasks to storage

        Args:
            tasks: Dictionary of task_id -> task_data
        """
        with self.lock:
            try:
                # Create backup
                if os.path.exists(self.store_path):
                    backup_path = f"{self.store_path}.bak"
                    try:
                        with open(self.store_path, 'r') as src:
                            with open(backup_path, 'w') as dst:
                                dst.write(src.read())
                    except Exception:
                        pass

                # Save tasks
                data = {
                    "version": 1,
                    "updated_at": datetime.now().isoformat(),
                    "tasks": tasks
                }

                with open(self.store_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Error saving tasks: {e}")
                raise

    def add_task(self, task: dict) -> bool:
        """
        Add a new task

        Args:
            task: Task data dictionary

        Returns:
            True if successful
        """
        with self.lock:
            tasks = self.load_tasks()
            task_id = task.get("id")

            if not task_id:
                raise ValueError("Task must have an 'id' field")

            if task_id in tasks:
                raise ValueError(f"Task with id '{task_id}' already exists")

            tasks[task_id] = task
            self.save_tasks(tasks)
        return True

    def update_task(self, task_id: str, updates: dict) -> bool:
        """
        Update an existing task

        Args:
            task_id: Task ID
            updates: Dictionary of fields to update

        Returns:
            True if successful
        """
        with self.lock:
            tasks = self.load_tasks()

            if task_id not in tasks:
                raise ValueError(f"Task '{task_id}' not found")

            tasks[task_id].update(updates)
            tasks[task_id]["updated_at"] = datetime.now().isoformat()

            self.save_tasks(tasks)
        return True

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task

        Args:
            task_id: Task ID

        Returns:
            True if successful
        """
        with self.lock:
            tasks = self.load_tasks()

            if task_id not in tasks:
                raise ValueError(f"Task '{task_id}' not found")

            del tasks[task_id]
            self.save_tasks(tasks)
        return True

    def get_task(self, task_id: str) -> Optional[dict]:
        """
        Get a specific task

        Args:
            task_id: Task ID

        Returns:
            Task data or None if not found
        """
        tasks = self.load_tasks()
        return tasks.get(task_id)

    def list_tasks(self, enabled_only: bool = False, agent_id: str = None) -> List[dict]:
        """
        List all tasks

        Args:
            enabled_only: If True, only return enabled tasks
            agent_id: If given, only return tasks owned by this Agent. Ownership
                is the task's *effective* owner: for an IM task that is the
                delivery instance's current binding (so re-binding a channel
                re-buckets its tasks with no data change), else the stored
                ``agent_id``, else the default Agent. This keeps the per-Agent
                list identical to what actually runs.

        Returns:
            List of task dictionaries
        """
        tasks = self.load_tasks()
        task_list = list(tasks.values())

        if enabled_only:
            task_list = [t for t in task_list if t.get("enabled", True)]

        if agent_id:
            from agent.tools.scheduler.integration import effective_task_agent_id
            default_id = ""
            try:
                from agent.registry import get_agent_registry
                default_id = get_agent_registry().default_agent_id
            except Exception:
                pass
            task_list = [
                t for t in task_list
                if (effective_task_agent_id(t) or default_id) == agent_id
            ]

        # Enabled tasks first, then newest-created on top (a task the user just
        # created should sit at the head of the list rather than wherever its
        # next_run_at happens to fall). created_at is an ISO string so a plain
        # string compare orders it chronologically; a legacy task missing it
        # sorts last within its group.
        def sort_key(t):
            enabled = t.get("enabled", True)
            created = t.get("created_at") or ""
            # Negate the created_at ordering for descending: pair the enabled
            # rank (ascending) with the created string reversed via a wrapper.
            return (0 if enabled else 1, _DescStr(created))

        task_list.sort(key=sort_key)

        return task_list

    def enable_task(self, task_id: str, enabled: bool = True) -> bool:
        """
        Enable or disable a task

        Args:
            task_id: Task ID
            enabled: True to enable, False to disable

        Returns:
            True if successful
        """
        return self.update_task(task_id, {"enabled": enabled})
