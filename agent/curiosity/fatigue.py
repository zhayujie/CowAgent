"""Feedback-window based push fatigue protection."""

from __future__ import annotations

from .state import CuriosityState


class FatigueGuard:
    def __init__(
        self,
        state: CuriosityState,
        window_size: int = 100,
        negative_threshold: float = 0.6,
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if not 0 <= negative_threshold <= 1:
            raise ValueError("negative_threshold must be between 0 and 1")
        self.state = state
        self.window_size = window_size
        self.negative_threshold = negative_threshold

    def record_feedback(self, accepted: bool) -> None:
        """Record one result without exposing a read/modify/write race."""
        with self.state._lock:
            window = list(self.state.data.get("feedback_window", ()))
            window.append(1 if accepted else 0)
            self.state.data["feedback_window"] = window[-self.window_size :]

    def is_fatigued(self) -> bool:
        with self.state._lock:
            window = list(self.state.data.get("feedback_window", ()))
        if not window:
            return False
        negative_ratio = window.count(0) / len(window)
        return negative_ratio >= self.negative_threshold
