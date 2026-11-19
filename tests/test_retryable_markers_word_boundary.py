"""Numbers containing a status code must not mark an error retryable.

A deterministic error whose text carries a count, such as "maximum value is
15000" (contains 500) or "limited to 1429 tokens" (contains 429), must fail
fast instead of sleeping through the retry budget and walking the fallback
chain. Real status codes keep retrying, on the text path and the image path.

Harness mirrors tests/test_chat_fallback_ratelimit.py.
"""
import pytest

from agent.protocol.agent_stream import AgentStreamExecutor, _is_retryable_error

ATTEMPTS = 3
TOTAL_CALLS = ATTEMPTS + 1  # the budget plus the final failing call


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

    def call_stream(self, request):  # replaced per-test
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
    slept = []
    monkeypatch.setattr("agent.protocol.agent_stream.time.sleep", lambda s: slept.append(s))
    return executor, slept


DETERMINISTIC_ERRORS = [
    "Invalid 'max_tokens': integer too large — maximum value is 15000",
    "payload limited to 1429 tokens per request",
    "messages must contain at most 25000 characters",
]


@pytest.mark.parametrize("error, retryable", [
    ("error code: 502 - bad gateway", True),
    ("http 503 service temporarily", True),
    ("status 429: too many requests", True),
    ("maximum value is 15000", False),
    ("payload limited to 1429 tokens per request", False),
])
def test_status_codes_are_matched_as_whole_words(error, retryable):
    # The image path keeps images on a transient failure with this same check.
    assert _is_retryable_error(error) is retryable


class TestCountsAreNotRetryable:

    @pytest.mark.parametrize("error", DETERMINISTIC_ERRORS)
    def test_a_deterministic_error_fails_fast(self, monkeypatch, error):
        model = _Model([{"provider": "openai", "model": "backup-1"}])

        def _call(request):
            model.calls.append(model.model)
            raise Exception(error)

        model.call_stream = _call
        executor, slept = _executor(model, monkeypatch)

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        # One call per link (the fallback chain gets a single attempt each),
        # no retries, no sleeps — the counts inside the message must not buy
        # the request a retry budget.
        assert model.calls == ["primary-model", "backup-1"], "a deterministic error retried"
        assert slept == [], "a deterministic error slept"

    def test_a_real_503_still_retries(self, monkeypatch):
        model = _Model([])

        def _call(request):
            model.calls.append(model.model)
            raise Exception("Service Unavailable: 503")

        model.call_stream = _call
        executor, slept = _executor(model, monkeypatch)

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert model.calls == ["primary-model"] * TOTAL_CALLS
        assert slept == [2, 4, 6]

    def test_textual_timeouts_still_retry(self, monkeypatch):
        model = _Model([])

        def _call(request):
            model.calls.append(model.model)
            raise Exception("Read timeout while streaming")

        model.call_stream = _call
        executor, _ = _executor(model, monkeypatch)

        with pytest.raises(Exception):
            executor._call_llm_stream(retry_on_empty=False)

        assert model.calls == ["primary-model"] * TOTAL_CALLS
