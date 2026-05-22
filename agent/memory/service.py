"""
Memory service for handling memory query operations via cloud protocol.

Provides a unified interface for listing and reading memory files,
callable from the cloud client (LinkAI) or a future web console.

Memory file layout (under workspace_root):
    MEMORY.md               -> type: global
    memory/2026-02-20.md    -> type: daily
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from common.log import logger


class MemoryService:
    """
    High-level service for memory file queries.
    Operates directly on the filesystem — no MemoryManager dependency.
    """

    def __init__(self, workspace_root: str):
        """
        :param workspace_root: Workspace root directory (e.g. ~/cow)
        """
        self.workspace_root = workspace_root
        self.memory_dir = os.path.join(workspace_root, "memory")

    # ------------------------------------------------------------------
    # list — paginated file metadata
    # ------------------------------------------------------------------
    def list_files(self, page: int = 1, page_size: int = 20, category: str = "memory") -> dict:
        """
        List memory or dream files with metadata (without content).

        Args:
            category: ``"memory"`` (default) — MEMORY.md + daily files;
                      ``"dream"``  — dream diary files from memory/dreams/
        """
        if category == "dream":
            files = self._list_dream_files()
        else:
            files = self._list_memory_files()

        total = len(files)
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "list": files[start:end],
        }

    def _list_memory_files(self) -> List[dict]:
        """MEMORY.md + memory/*.md (newest first)."""
        files: List[dict] = []

        global_path = os.path.join(self.workspace_root, "MEMORY.md")
        if os.path.isfile(global_path):
            files.append(self._file_info(global_path, "MEMORY.md", "global"))

        if os.path.isdir(self.memory_dir):
            daily_files = []
            for name in os.listdir(self.memory_dir):
                full = os.path.join(self.memory_dir, name)
                if os.path.isfile(full) and name.endswith(".md"):
                    daily_files.append((name, full))
            daily_files.sort(key=lambda x: x[0], reverse=True)
            for name, full in daily_files:
                files.append(self._file_info(full, name, "daily"))

        return files

    def _list_dream_files(self) -> List[dict]:
        """memory/dreams/*.md (newest first)."""
        files: List[dict] = []
        dreams_dir = os.path.join(self.memory_dir, "dreams")

        if os.path.isdir(dreams_dir):
            entries = []
            for name in os.listdir(dreams_dir):
                full = os.path.join(dreams_dir, name)
                if os.path.isfile(full) and name.endswith(".md"):
                    entries.append((name, full))
            entries.sort(key=lambda x: x[0], reverse=True)
            for name, full in entries:
                files.append(self._file_info(full, name, "dream"))

        return files

    # ------------------------------------------------------------------
    # content — read a single file
    # ------------------------------------------------------------------
    def get_content(self, filename: str, category: str = "memory") -> dict:
        """
        Read the full content of a memory or dream file.

        :param filename: File name, e.g. ``MEMORY.md``, ``2026-02-20.md``
        :param category: ``"memory"`` or ``"dream"``
        :return: dict with ``filename`` and ``content``
        :raises FileNotFoundError: if the file does not exist
        """
        path = self._resolve_path(filename, category)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Memory file not found: {filename}")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "filename": filename,
            "content": content,
        }

    # ------------------------------------------------------------------
    # dispatch — single entry point for protocol messages
    # ------------------------------------------------------------------
    def dispatch(self, action: str, payload: Optional[dict] = None) -> dict:
        """
        Dispatch a memory management action.

        :param action: ``list`` or ``content``
        :param payload: action-specific payload (supports ``category``: ``"memory"`` | ``"dream"``)
        :return: protocol-compatible response dict
        """
        payload = payload or {}
        try:
            if action == "list":
                page = payload.get("page", 1)
                page_size = payload.get("page_size", 20)
                category = payload.get("category", "memory")
                result_payload = self.list_files(page=page, page_size=page_size, category=category)
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "content":
                filename = payload.get("filename")
                if not filename:
                    return {"action": action, "code": 400, "message": "filename is required", "payload": None}
                category = payload.get("category", "memory")
                result_payload = self.get_content(filename, category=category)
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            else:
                return {"action": action, "code": 400, "message": f"unknown action: {action}", "payload": None}

        except ValueError as e:
            return {"action": action, "code": 403, "message": "invalid filename", "payload": None}
        except FileNotFoundError as e:
            return {"action": action, "code": 404, "message": str(e), "payload": None}
        except Exception as e:
            logger.error(f"[MemoryService] dispatch error: action={action}, error={e}")
            return {"action": action, "code": 500, "message": str(e), "payload": None}

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _resolve_path(self, filename: str, category: str = "memory") -> str:
        """
        Safely resolve a filename to its absolute path within the allowed directory.

        - ``MEMORY.md`` → ``{workspace_root}/MEMORY.md``
        - ``2026-02-20.md`` (memory) → ``{workspace_root}/memory/2026-02-20.md``
        - ``2026-02-20.md`` (dream) → ``{workspace_root}/memory/dreams/2026-02-20.md``

        Raises ValueError if the resolved path escapes the allowed directory.
        """
        if filename == "MEMORY.md":
            base_dir = self.workspace_root
        elif category == "dream":
            base_dir = os.path.join(self.memory_dir, "dreams")
        else:
            base_dir = self.memory_dir

        resolved = os.path.realpath(os.path.join(base_dir, filename))
        allowed = os.path.realpath(base_dir)

        if resolved != allowed and not resolved.startswith(allowed + os.sep):
            raise ValueError(f"Invalid filename: path traversal detected")

        return resolved

    @staticmethod
    def _file_info(path: str, filename: str, file_type: str) -> dict:
        """Build a file metadata dict."""
        stat = os.stat(path)
        updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "filename": filename,
            "type": file_type,
            "size": stat.st_size,
            "updated_at": updated_at,
        }
