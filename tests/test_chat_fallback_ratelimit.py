"""A rate limit should skip the wait and switch — but only when a backup exists.

Before this change a 429 always slept 30-60s per retry and only reached the
fallback after the whole budget was spent. With a chain configured that wait is
pure latency: the backup is a different provider with its own quota, so it can
answer immediately.

Without a chain there is nothing to switch to, so the old wait-it-out behaviour
must stay: failing a turn outright over a transient rate limit would be worse.
"""

import pytest

from agent.protocol.agent_stream import AgentStreamExecutor
from tests.sleep_stub import stub_sleep

RATE_LIMITED = "Rate limit reached (Status: 429)"
OTHER_ERROR = "server is busy (Status: 503)"
PRIMARY_ATTEMPTS = 4  # 1 attempt + max_retries (3)


class _Model:
    """Fails every call; reports chain availability like the real model."""

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
        self.calls.append(self._model)
        raise Exception(RATE_LIMITED)


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
    stub_sleep(monkeypatch)
    return executor


def _always_down(model, error):
    def _call(request):
        model.calls.append(model.model)
        raise Exception(error)
    return _call


class TestRateLimitWithABackup:
    """429 + chain => switch immediately, no retries, no sleeping."""

    def test_it_switches_on_the_first_attempt(self, monkeypatch):
        model = _Model([{"provider": "openai", "model": "backup-1"}])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(model, RATE_LIMITED))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        # Primary tried once, then straight to the backup — no 30s sleeps.
        assert executor.model.calls == ["primary-model", "backup-1"]

    def test_it_walks_the_whole_chain_without_retrying(self, monkeypatch):
        model = _Model([
            {"provider": "openai", "model": "backup-1"},
            {"provider": "qianfan", "model": "backup-2"},
            {"provider": "zhipu", "model": "backup-3"},
        ])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(model, RATE_LIMITED))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert executor.model.calls == [
            "primary-model", "backup-1", "backup-2", "backup-3",
        ]

    def test_it_never_sleeps(self, monkeypatch):
        """The point of the change: no waiting before switching."""
        model = _Model([{"provider": "openai", "model": "backup-1"}])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(model, RATE_LIMITED))
        slept = stub_sleep(monkeypatch)

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert slept == [], f"should not have slept, slept {slept}"


class TestRateLimitWithoutABackup:
    """429 + no chain => the old wait-it-out behaviour must be preserved."""

    def test_it_still_retries_the_full_budget(self, monkeypatch):
        model = _Model([])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(model, RATE_LIMITED))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert executor.model.calls == ["primary-model"] * PRIMARY_ATTEMPTS

    def test_it_still_sleeps_between_retries(self, monkeypatch):
        model = _Model([])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(model, RATE_LIMITED))
        slept = stub_sleep(monkeypatch)

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        # 30s, 45s, 60s — the pre-existing backoff, untouched.
        assert slept == [30, 45, 60]


class TestOtherErrorsAreUnaffected:
    """Only 429 gets the fast path; everything else keeps retrying."""

    def test_a_503_still_retries_even_with_a_chain(self, monkeypatch):
        model = _Model([{"provider": "openai", "model": "backup-1"}])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(model, OTHER_ERROR))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        # 503 is not a rate limit: full retry budget, then the backup.
        assert executor.model.calls == ["primary-model"] * PRIMARY_ATTEMPTS + ["backup-1"]


class TestNoFallbackSupport:
    """Plain models / doubles have no fallback_available — must not break."""

    def test_a_plain_model_keeps_retrying_on_429(self, monkeypatch):
        class Plain:
            def __init__(self):
                self.calls = []
                self.model = "primary-model"

            def call_stream(self, request):
                self.calls.append(self.model)
                raise Exception(RATE_LIMITED)

        model = Plain()
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", model.call_stream)

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert model.calls == ["primary-model"] * PRIMARY_ATTEMPTS
