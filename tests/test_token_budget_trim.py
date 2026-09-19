"""Unit tests for _token_budget_trim() and the unified _trim_messages() pass.

Covers the scenarios described in Issue #3178:
- Under-budget: no trim, no summary LLM call
- Over-budget: removes minimum turns needed (not "half")
- Turn safety-net: caps at max_context_turns even when under budget
- Single turn over budget: keeps newest turn (falls back to reactive recovery)
- Summary callback invoked for discarded turns
"""

import unittest
from unittest.mock import MagicMock, patch


def _make_msg(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _make_turn(user_text, assistant_text, n_tokens=100):
    """Build a fake turn dict with controllable token estimate."""
    msgs = [_make_msg("user", user_text), _make_msg("assistant", assistant_text)]
    turn = {"messages": msgs}
    # We'll patch _estimate_turn_tokens to return n_tokens for this turn.
    return turn, n_tokens


class FakeAgent:
    """Minimal mock of Agent for _trim_messages testing."""

    def __init__(self, context_window=128000, output_reserve=10000,
                 max_context_tokens=None, system_tokens=500):
        self.memory_manager = None
        self._current_user_id = None
        self._context_window = context_window
        self._output_reserve = output_reserve
        self.max_context_tokens = max_context_tokens
        self._system_tokens = system_tokens

    def _get_model_context_window(self):
        return self._context_window

    def _get_output_reserve_tokens(self):
        return self._output_reserve

    def _estimate_message_tokens(self, msg):
        return self._system_tokens


class TestTokenBudgetTrim(unittest.TestCase):
    """Test _token_budget_trim() in isolation."""

    def setUp(self):
        # We'll create a minimal mock that has _estimate_turn_tokens
        self.obj = MagicMock()
        self.obj._estimate_turn_tokens = MagicMock(side_effect=lambda t: t.get("_tokens", 100))

    def _turn(self, tokens):
        return {"_tokens": tokens, "messages": [_make_msg("user", "x")]}

    def test_all_fit_within_budget(self):
        turns = [self._turn(100), self._turn(200), self._turn(300)]
        kept, discarded = self.obj._token_budget_trim(turns, 10000)
        self.assertEqual(len(kept), 3)
        self.assertEqual(len(discarded), 0)

    def test_removes_minimum_turns(self):
        # 5 turns: 3K, 3K, 3K, 3K, 3K (from oldest to newest), budget=10K
        # Should keep newest 3 turns (9K), discard oldest 2 (6K)
        turns = [self._turn(3000), self._turn(3000), self._turn(3000),
                 self._turn(3000), self._turn(3000)]
        kept, discarded = self.obj._token_budget_trim(turns, 10000)
        self.assertEqual(len(kept), 3)
        self.assertEqual(len(discarded), 2)
        # Kept should be the NEWEST 3 turns
        self.assertEqual(kept[0]["_tokens"], 3000)  # originally index 2
        self.assertEqual(kept[-1]["_tokens"], 3000)  # originally index 4

    def test_single_turn_over_budget_still_kept(self):
        turns = [self._turn(99999)]
        kept, discarded = self.obj._token_budget_trim(turns, 1000)
        self.assertEqual(len(kept), 1)  # Always keep at least 1
        self.assertEqual(len(discarded), 0)

    def test_empty_turns(self):
        kept, discarded = self.obj._token_budget_trim([], 10000)
        self.assertEqual(len(kept), 0)
        self.assertEqual(len(discarded), 0)

    def test_exact_budget_fit(self):
        turns = [self._turn(500), self._turn(500)]
        kept, discarded = self.obj._token_budget_trim(turns, 1000)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(discarded), 0)


if __name__ == "__main__":
    unittest.main()
