"""Shared state for curiosity-engine components."""

from __future__ import annotations

import copy
import threading
from typing import Any, Dict, Optional


class CuriosityState:
    """Small thread-safe state container shared by v3 components.

    The lock is intentionally exposed to sibling components.  A component can
    therefore protect an entire read/modify/write operation instead of locking
    individual dictionary accesses and still losing updates between them.
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        self.data: Dict[str, Any] = copy.deepcopy(data or {})
        self._lock = threading.RLock()

    def snapshot(self) -> Dict[str, Any]:
        """Return an isolated copy suitable for persistence or inspection."""
        with self._lock:
            return copy.deepcopy(self.data)
