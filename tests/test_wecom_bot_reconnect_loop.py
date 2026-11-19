"""WeCom bot: a dropped long connection must reconnect, not nest.

The channel used to reconnect from inside its own on_close callback. That
callback runs on the worker thread, and the reconnect helper ends with
`self._ws_thread.join()`, so every disconnect left the dying thread parked in
the join of the thread it had just started: one thread (and one WebSocketApp)
parked for good per reconnect, until "can't start new thread" surfaces
somewhere unrelated.

It also retried every 5s no matter how long the outage had lasted, logging a
failure each time — the same shape the weixin long-poll loop was just fixed
for.

These tests drive the worker through disconnects with a fake socket. The
assertions fail on the old code: the reconnect loop and its backoff do not
exist there, so the recorded waits stay empty, one thread per reconnect gets
started, and a failed attempt never logs an ERROR.
"""

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channel.wecom_bot import wecom_bot_channel as wbc  # noqa: E402


class FakeStop:
    """Stop event that records the backoff waits instead of sleeping."""

    def __init__(self, stop_after_waits=None):
        self._set = False
        self.waits = []
        self._stop_after = stop_after_waits

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def clear(self):
        self._set = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self._stop_after is not None and len(self.waits) >= self._stop_after:
            self._set = True
        return self._set


class FakeApp:
    """Minimal WebSocketApp stand-in: keeps the callbacks for the driver."""

    instances = []

    def __init__(self, url, on_open=None, on_message=None, on_error=None, on_close=None):
        self.url = url
        self.on_open = on_open
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.closed = False
        FakeApp.instances.append(self)

    def send(self, payload):
        pass

    def close(self):
        self.closed = True


def _make_bot(stop_event):
    cls = wbc.WecomBotChannel.__wrapped__
    bot = cls.__new__(cls)
    bot._stop_event = stop_event
    bot._connected = False
    bot._ws = None
    bot._ws_thread = None
    bot._send_subscribe = lambda: None
    return bot


@pytest.fixture(autouse=True)
def fast_constants(monkeypatch):
    """Tiny backoff so the loop runs in milliseconds."""
    monkeypatch.setattr(wbc, "WS_RECONNECT_BASE_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(wbc, "WS_RECONNECT_MAX_SECONDS", 180, raising=False)
    monkeypatch.setattr(wbc, "WS_RECONNECT_STABLE_SECONDS", 60, raising=False)
    FakeApp.instances = []
    # Old code sleeps here, and would make the suite take 5s per reconnect.
    sleeps = []
    monkeypatch.setattr(wbc.time, "sleep", lambda s: sleeps.append(s))
    yield sleeps


def _drive(bot, monkeypatch, stop_after_connection=None, safety_limit=20):
    """Run _start_ws, dropping each connection as soon as it opens.

    Each fake run_forever call is one connection: it opens, closes and
    returns, which is what the real client does for a dropped socket. The loop
    ends when the stop event is set — by the test's wait budget, or after
    `stop_after_connection` attempts so the old recursive code also ends.
    """
    def fake_run_forever(app, ping_interval=0, reconnect=0):
        app.on_open(app)
        app.on_close(app, 1006, "connection closed")
        if (stop_after_connection is not None
                and len(FakeApp.instances) >= stop_after_connection):
            bot._stop_event.set()
        assert len(FakeApp.instances) <= safety_limit, "reconnect loop did not stop"

    monkeypatch.setattr(wbc, "websocket_app_run_forever", fake_run_forever)
    monkeypatch.setattr(wbc.websocket, "WebSocketApp", FakeApp)
    bot._start_ws()


def test_a_disconnect_does_not_start_another_worker_thread(monkeypatch):
    """The reconnect has to happen in the same thread, not a nested one."""
    import threading

    created = []
    real_thread = threading.Thread

    class RecordingThread(real_thread):
        def __init__(self, *args, **kwargs):
            created.append(kwargs.get("target"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(wbc.threading, "Thread", RecordingThread)
    bot = _make_bot(FakeStop())
    _drive(bot, monkeypatch, stop_after_connection=4)

    assert len(created) == 1, (
        f"{len(created)} worker threads were started for 3 reconnects; "
        "the reconnect must not come from inside on_close"
    )


def test_backoff_escalates_while_the_outage_lasts(monkeypatch):
    stop = FakeStop(stop_after_waits=3)
    bot = _make_bot(stop)
    _drive(bot, monkeypatch)

    assert stop.waits == [pytest.approx(0.01), pytest.approx(0.02), pytest.approx(0.04)], (
        f"waits were {stop.waits}; a persistent outage must back off, "
        "not retry every 5s forever"
    )


def test_backoff_is_capped(monkeypatch):
    monkeypatch.setattr(wbc, "WS_RECONNECT_BASE_SECONDS", 100.0, raising=False)
    monkeypatch.setattr(wbc, "WS_RECONNECT_MAX_SECONDS", 180.0, raising=False)
    stop = FakeStop(stop_after_waits=3)
    bot = _make_bot(stop)
    _drive(bot, monkeypatch)

    assert stop.waits == [100.0, 180.0, 180.0], f"waits were {stop.waits}"


def test_a_long_outage_is_logged_at_error_only_once(monkeypatch, caplog):
    stop = FakeStop(stop_after_waits=4)
    bot = _make_bot(stop)
    with caplog.at_level(logging.DEBUG, logger="common.log"):
        _drive(bot, monkeypatch)

    ours = [r for r in caplog.records if "[WecomBot]" in r.getMessage()]
    errors = [r for r in ours if r.levelno >= logging.ERROR]
    warnings = [r for r in ours
                if r.levelno == logging.WARNING and "still down" in r.getMessage()]
    assert len(errors) == 1, (
        f"expected one ERROR for the outage, got {[r.getMessage() for r in errors]}"
    )
    assert len(warnings) == 3, "each further attempt is a warning, not another error"


def test_stop_during_backoff_does_not_open_another_connection(monkeypatch):
    """stop() has to interrupt the wait, not wait it out and reconnect."""
    stop = FakeStop(stop_after_waits=1)
    bot = _make_bot(stop)
    _drive(bot, monkeypatch)

    assert len(FakeApp.instances) == 1, (
        f"{len(FakeApp.instances)} connections were opened after stop()"
    )
