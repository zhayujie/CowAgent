"""Concurrent interest-node creation."""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Dict, Optional

from .state import CuriosityState


class InterestGraph:
    def __init__(
        self,
        state: CuriosityState,
        save: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.state = state
        self._save = save

    def get_or_create(self, topic: str, **attributes: Any) -> Dict[str, Any]:
        """Atomically return the single node for ``topic``."""
        normalized = topic.strip()
        if not normalized:
            raise ValueError("topic must not be empty")
        with self.state._lock:
            graph = self.state.data.setdefault("interest_graph", {})
            node = graph.get(normalized)
            if node is None:
                node = {
                    "topic": normalized,
                    "created_at": time.time(),
                    **attributes,
                }
                graph[normalized] = node
                if self._save is not None:
                    self._save(copy.deepcopy(self.state.data))
            return copy.deepcopy(node)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self.state._lock:
            return copy.deepcopy(self.state.data.get("interest_graph", {}))
