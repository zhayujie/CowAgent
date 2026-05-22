"""
Task storage management for scheduler
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from common.utils import expand_path


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
        self.lock = threading.Lock()
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
        tasks = self.load_tasks()
        
        if task_id not in tasks:
            raise ValueError(f"Task '{task_id}' not found")
        
        # Update fields
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
    
    def list_tasks(self, enabled_only: bool = False) -> List[dict]:
        """
        List all tasks
        
        Args:
            enabled_only: If True, only return enabled tasks
            
        Returns:
            List of task dictionaries
        """
        tasks = self.load_tasks()
        task_list = list(tasks.values())
        
        if enabled_only:
            task_list = [t for t in task_list if t.get("enabled", True)]
        
        # Sort by next_run_at
        task_list.sort(key=lambda t: t.get("next_run_at", float('inf')))
        
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
