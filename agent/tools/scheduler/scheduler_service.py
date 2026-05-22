"""
Background scheduler service for executing scheduled tasks
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional
from croniter import croniter
from common.log import logger


def _parse_naive_local(iso_str: str) -> datetime:
    """Parse an ISO datetime and coerce it to tz-naive local time.

    The scheduler uses ``datetime.now()`` (tz-naive) for all comparisons,
    so any persisted timestamp must be normalized to the same flavor —
    otherwise comparing naive vs aware raises TypeError.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


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
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
    
    def start(self):
        """Start the scheduler service"""
        with self._lock:
            if self.running:
                logger.warning("[Scheduler] Service already running")
                return
            
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logger.debug("[Scheduler] Service started")
    
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
        logger.debug("[Scheduler] Scheduler loop started")
        
        while self.running:
            try:
                self._check_and_execute_tasks()
            except Exception as e:
                logger.error(f"[Scheduler] Error in scheduler loop: {e}")

            time.sleep(30)
    
    def _check_and_execute_tasks(self):
        """Check for due tasks and execute them"""
        now = datetime.now()
        tasks = self.task_store.list_tasks(enabled_only=True)
        
        for task in tasks:
            try:
                # Check if task is due
                if self._is_task_due(task, now):
                    logger.info(f"[Scheduler] Executing task: {task['id']} - {task['name']}")
                    self._execute_task(task)
                    
                    # Update next run time
                    next_run = self._calculate_next_run(task, now)
                    if next_run:
                        self.task_store.update_task(task['id'], {
                            "next_run_at": next_run.isoformat(),
                            "last_run_at": now.isoformat()
                        })
                    else:
                        # One-time task completed, remove it
                        self.task_store.delete_task(task['id'])
                        logger.info(f"[Scheduler] One-time task completed and removed: {task['id']}")
            except Exception as e:
                logger.error(f"[Scheduler] Error processing task {task.get('id')}: {e}")
    
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
            next_run = _parse_naive_local(next_run_str)

            # Check if task is overdue (e.g., service restart)
            if next_run < now:
                time_diff = (now - next_run).total_seconds()
                
                # If overdue by more than 5 minutes, skip this run and schedule next
                if time_diff > 300:  # 5 minutes
                    logger.warning(f"[Scheduler] Task {task['id']} is overdue by {int(time_diff)}s, skipping and scheduling next run")
                    
                    # For one-time tasks, remove them directly
                    schedule = task.get("schedule", {})
                    if schedule.get("type") == "once":
                        self.task_store.delete_task(task['id'])
                        logger.info(f"[Scheduler] One-time task {task['id']} expired, removed")
                        return False
                    
                    # For recurring tasks, calculate next run from now
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
                cron = croniter(expression, from_time)
                return cron.get_next(datetime)
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
                run_at = _parse_naive_local(run_at_str)
                if run_at > from_time:
                    return run_at
            except Exception as e:
                logger.error(
                    f"[Scheduler] Failed to parse once-task run_at "
                    f"{run_at_str!r}: {e}"
                )
            return None
        
        return None
    
    def _execute_task(self, task: dict):
        """
        Execute a task
        
        Args:
            task: Task dictionary
        """
        try:
            # Call the execute callback
            self.execute_callback(task)
        except Exception as e:
            logger.error(f"[Scheduler] Error executing task {task['id']}: {e}")
            # Update task with error
            self.task_store.update_task(task['id'], {
                "last_error": str(e),
                "last_error_at": datetime.now().isoformat()
            })
