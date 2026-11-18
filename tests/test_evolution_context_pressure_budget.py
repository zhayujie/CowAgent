"""The context-pressure trigger must use the same budget the trimmer uses.

``_trim_messages`` caps history at ``min(max_context_tokens, window - reserve)``.
The trigger used ``max_context_tokens`` alone whenever it was set, and the
shipped config sets it (``agent_max_context_tokens: 200000``). For a 128k model
the trimmer keeps history under ~102k, so it could never reach 80% of 200k and
the "context is close to its capacity" trigger never fired.
"""

import threading

import agent.evolution.trigger as trigger


class _Agent:
    def __init__(self, history_tokens, window, max_context_tokens=None):
        self.messages = [{"role": "user", "content": "x"}]
        self.messages_lock = threading.Lock()
        self.max_context_tokens = max_context_tokens
        self._history_tokens = history_tokens
        self._window = window

    def _estimate_message_tokens(self, message):
        return self._history_tokens

    def _get_model_context_window(self):
        return self._window

    def _get_output_reserve_tokens(self):
        return int(self._window * 0.2)


def test_default_cap_above_a_small_window_does_not_hide_pressure():
    # 128k window -> trimmer ceiling 102400; history is 88% of it.
    agent = _Agent(history_tokens=90_000, window=128_000, max_context_tokens=200_000)

    assert trigger._context_pressure_reached(agent)


def test_cap_below_the_window_still_sets_the_budget():
    agent = _Agent(history_tokens=45_000, window=1_000_000, max_context_tokens=50_000)
    assert trigger._context_pressure_reached(agent)

    agent = _Agent(history_tokens=30_000, window=1_000_000, max_context_tokens=50_000)
    assert not trigger._context_pressure_reached(agent)


def test_no_cap_uses_the_window_minus_reserve():
    assert trigger._context_pressure_reached(_Agent(history_tokens=90_000, window=128_000))
    assert not trigger._context_pressure_reached(_Agent(history_tokens=60_000, window=128_000))
