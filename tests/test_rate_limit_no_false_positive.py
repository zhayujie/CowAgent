"""Numbers containing "429" must not be read as HTTP 429.

The rate-limit classifier matched a bare '429' substring, so a retryable
error whose text merely contains 1429 or the uint32 cap 4294967295 (token
counts, byte counts) took the rate-limit fast path: with a fallback chain
the primary was switched away from immediately, and without one the backoff
jumped from seconds to the 30-60s rate-limit sleeps. Same class of bug as
the bare '400' documented at the top of agent_stream.py (fixed as
_RE_HTTP_400); this pins the word-bounded 429.

The harness mirrors tests/test_chat_fallback_ratelimit.py.
"""
import pytest

from agent.protocol.agent_stream import AgentStreamExecutor

PRIMARY_ATTEMPTS = 3


class _Model:
    def __init__(self, chain):
        self.chain = list(chain)
        self.calls = []
        self._model = "primary-model"
        self._depth = 0

    @property
    def model(self):
        return self._model

    def fallback_available(self):
        return self._depth < len(self.chain)

    def use_fallback(self):
        if self._depth >= len(self.chain):
            return False
        self._model = self.chain[self._depth]["model"]
        self._depth += 1
        return True

    def call_stream(self, request):  # replaced per-test via monkeypatch
        raise NotImplementedError


def _executor(model, monkeypatch):
    executor = AgentStreamExecutor.__new__(AgentStreamExecutor)
    executor.model = model
    executor.agent = None
    executor.messages = []
    executor.tools = {}
    executor.system_prompt = ""
    monkeypatch.setattr(executor, "_validate_and_fix_messages", lambda: None)
    monkeypatch.setattr(executor, "_prepare_messages", lambda: [])
    monkeypatch.setattr(executor, "_identify_complete_turns", lambda: [])
    monkeypatch.setattr(executor, "_emit_event", lambda *a, **k: None)
    monkeypatch.setattr(executor, "_is_thinking_enabled", lambda: False)
    monkeypatch.setattr("agent.protocol.agent_stream.time.sleep", lambda s: None)
    return executor


def _always_raise(model, error):
    def _call(request):
        model.calls.append(model.model)
        raise Exception(error)
    return _call


# Retryable (contains "timeout") but carries numbers with a 429 inside.
FALSE_POSITIVE_ERRORS = [
    "Read timeout after 1429ms while streaming",
    "Connection error fetching 4294967295 bytes",
]


class TestNumbersAreNotRateLimits:

    @pytest.mark.parametrize("error", FALSE_POSITIVE_ERRORS)
    def test_a_retryable_error_with_429_inside_keeps_the_primary(self, monkeypatch, error):
        model = _Model([{"provider": "openai", "model": "backup-1"}])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_raise(model, error))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        # Full retry budget on the primary before any switch — before the
        # word boundary it switched away after a single attempt.
        switched_at = model.calls.index("backup-1")
        assert switched_at >= PRIMARY_ATTEMPTS, \
            f"switched to the backup after only {switched_at} attempt(s)"

    def test_a_real_429_still_takes_the_fast_path(self, monkeypatch):
        model = _Model([{"provider": "openai", "model": "backup-1"}])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(
            executor.model, "call_stream",
            _always_raise(model, "Too many requests (Status: 429)"))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert model.calls == ["primary-model", "backup-1"]
