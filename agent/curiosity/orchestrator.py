"""Failure-isolated curiosity push orchestration."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class PushOrchestrator:
    def __init__(
        self,
        get_recent_messages: Callable[[], Any],
        fatigue_guard: Any,
        build_push: Callable[[Any], Any],
    ) -> None:
        self._get_recent_messages = get_recent_messages
        self.fatigue_guard = fatigue_guard
        self._build_push = build_push

    def orchestrate(self) -> Optional[Any]:
        """Return no push when any pipeline stage fails."""
        try:
            messages = self._get_recent_messages()
            if self.fatigue_guard.is_fatigued():
                return None
            return self._build_push(messages)
        except Exception:
            logger.exception("Curiosity push orchestration failed")
            return None
