"""QQ channel: one live session, and API rejections that say why.

The channel can be started again on the same instance (a restart does exactly
that), and the QQ platform pushes events to every open session — so a leftover
socket turns into duplicate replies. Separately, both credential and gateway
failures used to be reported without the platform's own error body, which is
the only thing that tells an IP-allowlist rejection from a bad secret.
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_channel():
    from channel.qq import qq_channel
    # @singleton hands back a factory function; the class lives in its closure.
    cls = next(cell.cell_contents for cell in qq_channel.QQChannel.__closure__
               if isinstance(cell.cell_contents, type))
    ch = cls.__new__(cls)
    ch._ws = None
    ch._generation = 0
    ch._last_api_error = ""
    ch._access_token = "token"
    ch._token_expires_at = float("inf")
    ch._token_lock = threading.Lock()
    ch._stop_event = MagicMock()
    ch._connected = False
    return ch


class SessionLifecycleTest(unittest.TestCase):

    def test_stop_supersedes_the_open_session(self):
        ch = _make_channel()
        ch._ws = MagicMock()

        ch.stop()

        self.assertEqual(ch._generation, 1, "stop must invalidate the old session")
        self.assertIsNone(ch._ws)
        self.assertFalse(ch._connected)

    def test_a_superseded_socket_does_not_reconnect(self):
        """The old socket's on_close fires after a new session took over."""
        ch = _make_channel()
        started = []

        with patch.object(ch, "_get_ws_url", return_value="wss://example/ws"), \
             patch("channel.qq.qq_channel.websocket.WebSocketApp") as ws_app, \
             patch("channel.qq.qq_channel.threading.Thread") as thread:
            thread.return_value = MagicMock()
            ch._start_ws()
            on_close = ws_app.call_args.kwargs["on_close"]

            # A newer session comes up, then the old socket finally closes.
            ch._generation += 1
            ch._stop_event.is_set.return_value = False
            with patch.object(ch, "_start_ws", side_effect=lambda: started.append(1)):
                on_close(None, 1006, "closed")

        self.assertEqual(started, [], "a superseded socket must not reconnect itself")


class HeartbeatWatchdogTest(unittest.TestCase):
    """A silently-dead connection (no heartbeat ACKs) must force a reconnect.

    ping_interval alone can miss an application-layer stall where the socket is
    up but the gateway has gone quiet, so the heartbeat loop watches ACK
    freshness and closes the socket when it goes stale, routing into _on_close.
    """

    def test_missing_acks_force_the_socket_closed(self):

        ch = _make_channel()
        ch._connected = True
        ch._last_seq = 5
        ws = MagicMock()
        ch._ws = ws
        ch._heartbeat_thread = None

        # Real Event so the loop's is_set() gates behave normally; we stop it
        # from the fake wait() after the first tick to keep the test bounded.
        ch._stop_event = threading.Event()

        # ACK clock is far in the past -> the very first check sees a stall.
        with patch("channel.qq.qq_channel.time.time", return_value=10_000.0):
            def fake_wait(_):
                # Pretend a full interval elapsed while the gateway stayed silent.
                ch._last_heartbeat_ack = 0.0
                return False
            ch._stop_event = MagicMock()
            ch._stop_event.is_set.return_value = False
            ch._stop_event.wait.side_effect = fake_wait

            ch._start_heartbeat(1000)
            ch._heartbeat_thread.join(timeout=2)

        ws.close.assert_called_once()

    def test_fresh_acks_keep_the_connection(self):
        ch = _make_channel()
        ch._connected = True
        ch._last_seq = 5
        ws = MagicMock()
        ch._ws = ws
        ch._heartbeat_thread = None

        calls = {"n": 0}

        with patch("channel.qq.qq_channel.time.time", return_value=10_000.0):
            def fake_wait(_):
                # ACK stays fresh (== now); loop should not close, and we stop
                # after two ticks so the test terminates.
                ch._last_heartbeat_ack = 10_000.0
                calls["n"] += 1
                if calls["n"] >= 2:
                    ch._connected = False
                return False
            ch._stop_event = MagicMock()
            ch._stop_event.is_set.return_value = False
            ch._stop_event.wait.side_effect = fake_wait

            ch._start_heartbeat(1000)
            ch._heartbeat_thread.join(timeout=2)

        ws.close.assert_not_called()


class ApiErrorReportingTest(unittest.TestCase):

    def test_a_refused_token_keeps_its_reason(self):
        ch = _make_channel()
        ch._access_token = ""
        ch._token_expires_at = 0
        ch.app_id, ch.app_secret = "id", "secret"
        resp = MagicMock(status_code=200, text='{"code":10004,"message":"机器人不存在"}')
        resp.json.return_value = {"code": 10004, "message": "机器人不存在"}

        with patch("channel.qq.qq_channel.requests.post", return_value=resp):
            ch._refresh_access_token()

        self.assertIn("机器人不存在", ch._last_api_error)
        self.assertEqual(ch._access_token, "")

    def test_a_refused_token_does_not_block_the_next_retry(self):
        """The expiry must stay put, or a hiccup silences the channel for 2h."""
        ch = _make_channel()
        ch._token_expires_at = 0
        ch.app_id, ch.app_secret = "id", "secret"
        resp = MagicMock(status_code=200, text='{"code":100007,"message":"appid invalid"}')
        resp.json.return_value = {"code": 100007}

        with patch("channel.qq.qq_channel.requests.post", return_value=resp):
            ch._refresh_access_token()

        self.assertEqual(ch._token_expires_at, 0)

    def test_a_rejected_gateway_keeps_the_platform_body(self):
        ch = _make_channel()
        body = '{"message":"ip not in whitelist","code":11298,"trace_id":"abc"}'
        resp = MagicMock(status_code=400, text=body)

        with patch("channel.qq.qq_channel.requests.get", return_value=resp):
            url = ch._get_ws_url()

        self.assertEqual(url, "")
        self.assertIn("11298", ch._last_api_error)
        self.assertIn("400", ch._last_api_error)


if __name__ == "__main__":
    unittest.main()
