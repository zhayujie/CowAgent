"""A provider that can't be reached fails the turn at once, with a readable reason.

Retrying an address that didn't answer only multiplied the wait: four attempts
at a blocked host left the user on a spinner for minutes before a raw urllib3
traceback string appeared. A backup model is still worth switching to, and a
read timeout, where the provider was reached, keeps its retries.
"""

import pytest

from agent.protocol.agent_stream import AgentStreamExecutor, _is_unreachable_error
from tests.sleep_stub import stub_sleep

CONNECT_TIMEOUT = (
    "HTTPSConnectionPool(host='generativelanguage.googleapis.com', port=443): Max retries exceeded with url: "
    "/v1beta/models/gemini-4-argon:streamGenerateContent?alt=sse (Caused by ConnectTimeoutError("
    "<urllib3.connection.HTTPSConnection object at 0x1>, 'Connection to generativelanguage.googleapis.com "
    "timed out. (connect timeout=15)')) (Status: 500, Code: , Type: )"
)
LOOKUP_FAILED = (
    "HTTPSConnectionPool(host='api.example.com', port=443): Max retries exceeded with url: /v1/chat "
    "(Caused by NameResolutionError(\"<urllib3.connection.HTTPSConnection object at 0x1>: Failed to resolve "
    "'api.example.com' ([Errno 8] nodename nor servname provided, or not known)\"))"
)
READ_TIMEOUT = (
    "HTTPSConnectionPool(host='api.example.com', port=443): Read timed out. (read timeout=60) (Status: 500)"
)
PRIMARY_ATTEMPTS = 4  # 1 attempt + max_retries (3)


class _Model:
    def __init__(self, error, chain=()):
        self.error = error
        self.chain = list(chain)
        self.calls = []
        self.model = "primary-model"
        self._depth = 0

    def fallback_available(self):
        return self._depth < len(self.chain)

    def use_fallback(self):
        if self._depth >= len(self.chain):
            return False
        self.model = self.chain[self._depth]["model"]
        self._depth += 1
        return True

    def call_stream(self, request):
        self.calls.append(self.model)
        raise Exception(self.error)


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


@pytest.mark.parametrize("error", [CONNECT_TIMEOUT, LOOKUP_FAILED])
def test_an_unreachable_provider_is_tried_once(monkeypatch, error):
    model = _Model(error)
    executor = _executor(model, monkeypatch)

    with pytest.raises(Exception) as caught:
        executor._call_llm_stream(retry_on_empty=False)

    assert model.calls == ["primary-model"]
    message = str(caught.value)
    assert "HTTPSConnectionPool" not in message
    host = "generativelanguage.googleapis.com" if error is CONNECT_TIMEOUT else "api.example.com"
    assert host in message


def test_an_unreachable_provider_still_hands_over_to_a_backup(monkeypatch):
    model = _Model(CONNECT_TIMEOUT, chain=[{"provider": "openai", "model": "backup-1"}])
    executor = _executor(model, monkeypatch)

    with pytest.raises(Exception):
        executor._call_llm_stream(retry_on_empty=False)

    assert model.calls == ["primary-model", "backup-1"]


def test_a_read_timeout_keeps_its_retries(monkeypatch):
    model = _Model(READ_TIMEOUT)
    executor = _executor(model, monkeypatch)

    with pytest.raises(Exception) as caught:
        executor._call_llm_stream(retry_on_empty=False)

    assert len(model.calls) == PRIMARY_ATTEMPTS
    assert "Read timed out" in str(caught.value)


@pytest.mark.parametrize("text", [
    "connection refused",
    "[Errno 101] Network is unreachable",
    "Failed to establish a new connection: [Errno 113] No route to host",
])
def test_other_ways_of_not_reaching_the_host_count(text):
    assert _is_unreachable_error(text.lower())


@pytest.mark.parametrize("text", [READ_TIMEOUT, "server is busy (Status: 503)", "Rate limit reached (Status: 429)"])
def test_a_reached_provider_does_not_count(text):
    assert not _is_unreachable_error(text.lower())
