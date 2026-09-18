"""Atomic JSON checkpoints for a single Agent run."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CHECKPOINT_VERSION = 1


class CheckpointManager:
    """Manage checkpoints using temporary-file plus-rename writes."""

    def __init__(self, checkpoint_dir: str):
        self.dir = Path(checkpoint_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        """Map an arbitrary session id to a traversal-safe filename."""
        return self.dir / f"{hashlib.sha256(session_id.encode('utf-8')).hexdigest()}.json"

    def save(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        turn: int,
    ) -> None:
        """Atomically persist the resumable state after a completed turn."""
        path = self.path_for(session_id)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.dir,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                json.dump(
                    {
                        "version": CHECKPOINT_VERSION,
                        "session_id": session_id,
                        "turn": turn,
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                        "messages": messages,
                    },
                    tmp_file,
                    ensure_ascii=False,
                    default=str,
                )
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def load(self, session_id: str) -> Optional[Tuple[List[Dict[str, Any]], int]]:
        """Return ``(messages, turn)``, or ``None`` for unusable checkpoints."""
        try:
            with self.path_for(session_id).open("r", encoding="utf-8") as file:
                data = json.load(file)
            messages, turn = data["messages"], data["turn"]
            if data.get("version") != CHECKPOINT_VERSION:
                return None
            if not isinstance(messages, list) or not isinstance(turn, int):
                return None
            return messages, turn
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def clear(self, session_id: str) -> bool:
        """Remove a checkpoint, reporting whether cleanup succeeded."""
        try:
            self.path_for(session_id).unlink(missing_ok=True)
            return True
        except OSError:
            return False
