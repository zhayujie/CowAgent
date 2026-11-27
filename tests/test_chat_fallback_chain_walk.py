"""The executor must walk the whole chain, one attempt per link.

These drive ``_call_llm_stream`` for real (with a stubbed transport) rather
than the model's ``use_fallback``, because the two behaviors that matter live
in the executor: that a failing link advances to the next one instead of
ending the turn, and that a link gets *one* attempt rather than the primary's
full retry budget.

The single-attempt rule is what keeps a chain usable: with the primary's
backoff (30s+ per rate-limited retry) a three-link chain would sleep past the
web channel's SSE idle timeout before the last link was even tried, and the
user would see a dropped connection instead of a reply.
"""

import pytest

from agent.protocol.agent_stream import AgentStreamExecutor
from tests.sleep_stub import stub_sleep


class _FailingModel:
    """A model that reports failure through use_fallback, like the real one."""

    def __init__(self, chain):
        self.chain = list(chain)
        self.calls = []          # model name per call attempt
        self._model = "primary-model"
        self._depth = 0

    @property
    def model(self):
        return self._model

    def use_fallback(self):
        if self._depth >= len(self.chain):
            return False
        self._model = self.chain[self._depth]["model"]
        self._depth += 1
        return True

    def call_stream(self, request):  # replaced per-test via monkeypatch
        self.calls.append(self._model)
        raise Exception("provider is down (Status: 503)")


def _executor(model, monkeypatch):
    """An executor reduced to the retry/fallback path alone."""
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
    # Never actually sleep — the point of these tests is the call sequence.
    stub_sleep(monkeypatch)
    return executor


def _always_down(executor, error="provider is down (Status: 503)"):
    def _call(request):
        executor.model.calls.append(executor.model.model)
        raise Exception(error)
    return _call


# The primary gets its own full retry budget before the chain is touched:
# 1 attempt + max_retries (3) retries.
PRIMARY_ATTEMPTS = 4



class TestWalkingTheChain:
    def test_a_failed_link_advances_to_the_next(self, monkeypatch):
        model = _FailingModel([
            {"provider": "openai", "model": "backup-1"},
            {"provider": "qianfan", "model": "backup-2"},
            {"provider": "zhipu", "model": "backup-3"},
        ])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(executor))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        # Every model was tried, in chain order, right after the primary.
        assert executor.model.calls == (
            ["primary-model"] * PRIMARY_ATTEMPTS
            + ["backup-1", "backup-2", "backup-3"]
        )

    def test_the_whole_chain_is_reported_when_it_runs_out(self, monkeypatch):
        """Blaming only the last link reads as 'that one model is broken'
        when in fact each one was tried and each one failed."""
        model = _FailingModel([
            {"provider": "openai", "model": "backup-1"},
            {"provider": "qianfan", "model": "backup-2"},
        ])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(executor))

        with pytest.raises(Exception) as exc:
            executor._call_llm_stream(retry_on_empty=False)

        message = str(exc.value)
        for name in ("primary-model", "backup-1", "backup-2"):
            assert name in message, f"the failure should name {name}"

    def test_a_link_gets_one_attempt_not_the_primarys_budget(self, monkeypatch):
        """The primary retries; a link is tried once and then left behind."""
        model = _FailingModel([{"provider": "openai", "model": "backup-1"}])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(executor))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False, max_retries=3)

        assert executor.model.calls == ["primary-model"] * PRIMARY_ATTEMPTS + ["backup-1"]

    def test_a_long_chain_is_walked_in_full(self, monkeypatch):
        """No cap: five links means five tries, not one."""
        model = _FailingModel([
            {"provider": "openai", "model": f"backup-{i}"} for i in range(5)
        ])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(executor.model, "call_stream", _always_down(executor))

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert executor.model.calls == (
            ["primary-model"] * PRIMARY_ATTEMPTS
            + [f"backup-{i}" for i in range(5)]
        )

    def test_the_turn_stops_at_the_link_that_answers(self, monkeypatch):
        model = _FailingModel([
            {"provider": "openai", "model": "backup-1"},
            {"provider": "qianfan", "model": "backup-2"},
        ])
        executor = _executor(model, monkeypatch)
        attempts = {"n": 0}

        def _call(request):
            model.calls.append(model.model)
            attempts["n"] += 1
            if attempts["n"] <= PRIMARY_ATTEMPTS:
                raise Exception("provider is down (Status: 503)")
            return iter([])  # backup-1 answers (with an empty stream)

        monkeypatch.setattr(executor.model, "call_stream", _call)
        result = executor._call_llm_stream(retry_on_empty=False)

        assert result is not None
        assert executor.model.calls == ["primary-model"] * PRIMARY_ATTEMPTS + ["backup-1"]
        # The second link was never needed.
        assert "backup-2" not in executor.model.calls


class TestNoChainConfigured:
    """Without a fallback the turn must still fail the way it always did."""

    def test_the_original_error_is_raised_untouched(self, monkeypatch):
        model = _FailingModel([])
        executor = _executor(model, monkeypatch)
        monkeypatch.setattr(
            executor.model, "call_stream",
            _always_down(executor, "boom (Status: 503)"),
        )

        with pytest.raises(Exception) as exc:
            executor._call_llm_stream(retry_on_empty=False)

        # Not wrapped in the "chain exhausted" message — there is no chain.
        assert "boom" in str(exc.value)
        assert "fallback" not in str(exc.value).lower()
        assert executor.model.calls == ["primary-model"] * PRIMARY_ATTEMPTS
