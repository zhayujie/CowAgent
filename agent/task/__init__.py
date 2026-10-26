"""Background tasks, approvals and notifications.

Off unless ``task.enabled`` is set: with it off no tool, gate, board or
scheduler change is active. Modules import lazily from here to keep the
agent's import graph unchanged when the feature is unused.
"""

from agent.task.settings import is_enabled, task_settings

__all__ = ["is_enabled", "task_settings"]
