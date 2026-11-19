"""Retry loop of the Feishu websocket thread (_startup_websocket)."""

import ssl
from unittest.mock import MagicMock

import pytest

pytest.importorskip("lark_oapi")

from channel.feishu import feishu_channel
from channel.feishu.feishu_channel import FeiShuChanel


class _StopAfter:
    """Stand-in for _ws_stop_event: records backoff waits, signals stop after N."""

    def __init__(self, waits_before_stop):
        self.waits_before_stop = waits_before_stop
        self.timeouts = []

    def wait(self, timeout=None):
        self.timeouts.append(timeout)
        return len(self.timeouts) > self.waits_before_stop

    def set(self):
        pass

    def clear(self):
        pass


@pytest.fixture(autouse=True)
def _restore_ssl():
    original_default = ssl.create_default_context
    original_unverified = ssl._create_unverified_context
    yield
    ssl.create_default_context = original_default
    ssl._create_unverified_context = original_unverified


def _run(monkeypatch, outcomes, waits_before_stop=10):
    """Drive _startup_websocket with Client.start() following ``outcomes``.

    Each outcome is an exception to raise, or None for a connection that
    comes up (start() returns). Returns per-attempt TLS verification state,
    the stop-event stand-in and the reported startup errors.
    """
    original_default = ssl.create_default_context
    verified = []
    script = list(outcomes)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            verified.append(ssl.create_default_context is original_default)
            outcome = script.pop(0) if script else None
            if outcome is not None:
                raise outcome

    monkeypatch.setattr(feishu_channel, "_ensure_lark_imported", lambda: None)
    monkeypatch.setattr(feishu_channel, "lark", MagicMock(), raising=False)
    monkeypatch.setattr(
        feishu_channel, "_new_lark_ws_client_module",
        lambda loop: MagicMock(Client=FakeClient))

    channel = FeiShuChanel()
    stop = _StopAfter(waits_before_stop)
    reported = []
    monkeypatch.setattr(channel, "feishu_app_id", "cli_test", raising=False)
    monkeypatch.setattr(channel, "feishu_app_secret", "secret", raising=False)
    monkeypatch.setattr(channel, "_ws_client", None, raising=False)
    monkeypatch.setattr(channel, "_ws_thread", None, raising=False)
    monkeypatch.setattr(channel, "_ws_stop_event", stop, raising=False)
    monkeypatch.setattr(channel, "report_startup_error", reported.append)

    channel._startup_websocket()
    return verified, stop, reported


def test_non_ssl_failures_keep_tls_verification(monkeypatch):
    verified, stop, reported = _run(
        monkeypatch, [RuntimeError("invalid app_secret")] * 7, waits_before_stop=6)

    assert verified == [True] * 7
    assert ssl.create_default_context.__module__ == "ssl"
    assert stop.timeouts == [5, 10, 20, 40, 60, 60, 60]
    assert reported == ["invalid app_secret"]


def test_transient_failure_then_connect_keeps_tls_verification(monkeypatch):
    verified, stop, reported = _run(
        monkeypatch, [ConnectionError("dns timeout"), None])

    assert verified == [True, True]
    assert ssl.create_default_context.__module__ == "ssl"
    assert stop.timeouts == [5]
    assert reported == ["dns timeout"]


def test_certificate_error_disables_verification_once_and_retries_immediately(monkeypatch):
    cert_error = ssl.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    verified, stop, reported = _run(
        monkeypatch, [cert_error, cert_error, None])

    assert verified == [True, False, False]
    assert stop.timeouts == [5]
    assert len(reported) == 1


def test_stop_during_backoff_exits_loop(monkeypatch):
    verified, stop, reported = _run(
        monkeypatch, [RuntimeError("boom")] * 5, waits_before_stop=0)

    assert verified == [True]
    assert stop.timeouts == [5]
    assert reported == ["boom"]
