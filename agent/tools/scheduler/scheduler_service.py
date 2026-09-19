"""
Background scheduler service for executing scheduled tasks
"""

import time
import inspect
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

from common.log import logger
from agent.tools.scheduler.time_utils import (
    next_cron_occurrence,
    normalize_task_timestamps,
    parse_utc,
    task_timezone,
    utc_now,
)


def _callable_accepts_two_positional(fn: Callable) -> bool:
    """Return True if ``fn`` can be called with two positional args.

    Used to decide whether the execute callback accepts a ``trigger`` argument
    in addition to the task, so we can forward it without breaking older
    single-arg callbacks. Falls back to False if the signature can't be read.
    """
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return True
    positional = [
        p for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 2


def _migrate_naive_timestamps(task: dict) -> dict:
    """Normalize persisted scheduling timestamps for one scheduler read.

    Aware values are converted to UTC. Naive values keep their historical
    server-local meaning, unless the task explicitly declares an IANA timezone.
    The store is not rewritten here so upgrading never mutates unrelated tasks.
    """
    return normalize_task_timestamps(task)


class SchedulerService:
    """
    Background service that executes scheduled tasks
    """
    
    def __init__(self, task_store, execute_callback: Callable):
        """
        Initialize scheduler service
        
        Args:
            task_store: TaskStore instance
            execute_callback: Function to call when executing a task
        """
        self.task_store = task_store
        self.execute_callback = execute_callback
        # Whether the callback declares a second positional slot for ``trigger``.
        # Computed once so _execute_task can forward the run source without
        # risking a TypeError-based misdetection at call time.
        self._callback_accepts_trigger = _callable_accepts_two_positional(execute_callback)
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._active_task_ids = set()
    
    def start(self):
        """Start the scheduler service"""
        with self._lock:
            if self.running:
                logger.warning("[Scheduler] Service already running")
                return
            
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
    
    def stop(self):
        """Stop the scheduler service"""
        with self._lock:
            if not self.running:
                return
            
            self.running = False
            if self.thread:
                self.thread.join(timeout=5)
            logger.info("[Scheduler] Service stopped")
    
    def _run_loop(self):
        """Main scheduler loop"""
        logger.info("[Scheduler] Scheduler loop started")
        
        while self.running:
            try:
                self._check_and_execute_tasks()
            except Exception as e:
                logger.error(f"[Scheduler] Error in scheduler loop: {e}")

            time.sleep(30)
    
    def _check_and_execute_tasks(self):
        """Check for due tasks and execute them"""
        now = utc_now()
        tasks = []
        for raw_task in self.task_store.list_tasks(enabled_only=True):
            try:
                tasks.append(_migrate_naive_timestamps(raw_task))
            except Exception as e:
                logger.error(
                    f"[Scheduler] Failed to normalize timestamps for task "
                    f"{raw_task.get('id')}: {e}"
                )
        
        for task in tasks:
            try:
                if self._is_task_due(task, now):
                    logger.info(f"[Scheduler] Executing task: {task['id']} - {task['name']}")
                    if not self._claim_task(task['id']):
                        logger.info(
                            f"[Scheduler] Task {task['id']} is already running; skipping this tick"
                        )
                        continue
                    try:
                        ok = self._execute_task(task)
                    finally:
                        self._release_task(task['id'])
                    if not ok:
                        # Leave next_run_at as-is so the next loop retries.
                        # Cron tasks within the catch-up window will keep
                        # firing; beyond it _is_task_due will reschedule.
                        logger.warning(
                            f"[Scheduler] Task {task['id']} delivery failed, will retry next tick"
                        )
                        continue

                    next_run = self._calculate_next_run(task, now)
                    if next_run:
                        self.task_store.update_task(task['id'], {
                            "next_run_at": next_run.isoformat(),
                            "last_run_at": now.isoformat()
                        })
                    else:
                        self.task_store.delete_task(task['id'])
                        logger.info(f"[Scheduler] One-time task completed and removed: {task['id']}")
            except Exception as e:
                logger.error(f"[Scheduler] Error processing task {task.get('id')}: {e}")

    def run_task_now(self, task_id: str) -> None:
        """Queue one immediate execution without changing the task schedule.

        Disabled and one-time tasks may be run manually for testing. The
        stored ``next_run_at`` remains unchanged, so a manual run never
        consumes or delays the next scheduled occurrence.

        Raises:
            ValueError: if the task does not exist.
            RuntimeError: if the same task is already executing.
        """
        task = _migrate_naive_timestamps(self.task_store.get_task(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found")
        if not self._claim_task(task_id):
            raise RuntimeError(f"Task '{task_id}' is already running")

        def _run():
            now = utc_now()
            try:
                logger.info(f"[Scheduler] Manually executing task: {task_id} - {task.get('name', '')}")
                ok = self._execute_task(task, trigger="manual")
                if ok:
                    self.task_store.update_task(task_id, {
                        "last_run_at": now.isoformat(),
                        "last_manual_run_at": now.isoformat(),
                    })
                    logger.info(f"[Scheduler] Manual execution completed: {task_id}")
                else:
                    logger.warning(f"[Scheduler] Manual execution failed: {task_id}")
            finally:
                self._release_task(task_id)

        threading.Thread(
            target=_run,
            daemon=True,
            name=f"scheduler-manual-{task_id}",
        ).start()

    def _claim_task(self, task_id: str) -> bool:
        """Prevent scheduled and manual runs of the same task from overlapping."""
        with self._execution_lock:
            if task_id in self._active_task_ids:
                return False
            self._active_task_ids.add(task_id)
            return True

    def _release_task(self, task_id: str) -> None:
        with self._execution_lock:
            self._active_task_ids.discard(task_id)
    
    def _is_task_due(self, task: dict, now: datetime) -> bool:
        """
        Check if a task is due to run
        
        Args:
            task: Task dictionary
            now: Current datetime
            
        Returns:
            True if task should run now
        """
        next_run_str = task.get("next_run_at")
        if not next_run_str:
            # Calculate initial next_run_at
            next_run = self._calculate_next_run(task, now)
            if next_run:
                self.task_store.update_task(task['id'], {
                    "next_run_at": next_run.isoformat()
                })
                return False
            return False
        
        try:
            next_run = parse_utc(next_run_str, task_timezone(task))

            if next_run < now:
                time_diff = (now - next_run).total_seconds()
                schedule = task.get("schedule", {})
                schedule_type = schedule.get("type")

                # Catch-up window: fire if we're within 10 minutes of the
                # scheduled tick. Beyond that we'd rather skip than push a
                # stale daily report to the user.
                if time_diff <= 600:
                    return True

                logger.warning(
                    f"[Scheduler] Task {task['id']} is overdue by {int(time_diff)}s, "
                    f"skipping and scheduling next run"
                )

                if schedule_type == "once":
                    self.task_store.delete_task(task['id'])
                    logger.info(f"[Scheduler] One-time task {task['id']} expired, removed")
                    return False

                next_next_run = self._calculate_next_run(task, now)
                if next_next_run:
                    self.task_store.update_task(task['id'], {
                        "next_run_at": next_next_run.isoformat()
                    })
                    logger.info(f"[Scheduler] Rescheduled task {task['id']} to {next_next_run}")
                return False

            return now >= next_run
        except Exception as e:
            logger.error(
                f"[Scheduler] Failed to evaluate due-state for task "
                f"{task.get('id')} (next_run_at={next_run_str!r}): {e}"
            )
            return False
    
    def _calculate_next_run(self, task: dict, from_time: datetime) -> Optional[datetime]:
        """
        Calculate next run time for a task
        
        Args:
            task: Task dictionary
            from_time: Calculate from this time
            
        Returns:
            Next run datetime or None for one-time tasks
        """
        schedule = task.get("schedule", {})
        schedule_type = schedule.get("type")
        
        if schedule_type == "cron":
            # Cron expression
            expression = schedule.get("expression")
            if not expression:
                return None
            
            try:
                return next_cron_occurrence(
                    expression, from_time, task_timezone(task)
                )
            except Exception as e:
                logger.error(f"[Scheduler] Invalid cron expression '{expression}': {e}")
                return None
        
        elif schedule_type == "interval":
            # Interval in seconds
            seconds = schedule.get("seconds", 0)
            if seconds <= 0:
                return None
            return from_time + timedelta(seconds=seconds)
        
        elif schedule_type == "once":
            # One-time task at specific time
            run_at_str = schedule.get("run_at")
            if not run_at_str:
                return None
            
            try:
                run_at = parse_utc(run_at_str, task_timezone(task))
                if run_at > from_time:
                    return run_at
            except Exception as e:
                logger.error(
                    f"[Scheduler] Failed to parse once-task run_at "
                    f"{run_at_str!r}: {e}"
                )
            return None
        
        return None
    
    def _execute_task(self, task: dict, trigger: str = "scheduled") -> bool:
        """
        Execute a task.

        ``trigger`` records how the run fired — ``"scheduled"`` for the timer
        loop, ``"manual"`` for a user-initiated "run now" — and is forwarded to
        the callback so run history can tell the two sources apart.

        Returns True if delivery succeeded (caller should advance state),
        False if it failed (caller should keep next_run_at so the next
        loop iteration retries). Callback may return None for legacy
        behaviour, treated as success.
        """
        try:
            # Pass ``trigger`` only when the callback declares a slot for it, so
            # older single-arg callbacks keep working. We inspect the signature
            # (rather than catch TypeError) to avoid mistaking a TypeError raised
            # *inside* the callback for an arity mismatch and re-running the task.
            if self._callback_accepts_trigger:
                result = self.execute_callback(task, trigger)
            else:
                result = self.execute_callback(task)
            return False if result is False else True
        except Exception as e:
            logger.error(f"[Scheduler] Error executing task {task['id']}: {e}")
            self.task_store.update_task(task['id'], {
                "last_error": str(e),
                "last_error_at": utc_now().isoformat()
            })
            return False
