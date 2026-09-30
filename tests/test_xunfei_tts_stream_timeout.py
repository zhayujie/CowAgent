"""What a Xunfei TTS call does when the provider stops answering.

``xunfei_tts`` hands the whole text to the stream and then waits for the audio
frames — it only closes once the server reports the last one (``status == 2``,
in ``on_message``). Until then ``run_forever`` is the only thing running, and it
was started with neither a timeout nor a ping, so nothing is ever sent that
could fail: a provider that accepts the connection and then goes quiet leaves
the call blocked inside ``run_forever`` for good. The voice turn never finishes,
the user gets nothing at all, and the thread stays parked.

Pinging bounds it. With ``ping_interval``/``ping_timeout`` set, websocket-client
ends the loop with ``WebSocketTimeoutException`` instead of blocking, and —
because ``run_forever`` only hands that to ``on_error`` and returns — the
failure is recorded and raised, so ``XunfeiVoice.textToVoice`` turns it into an
ERROR reply rather than a path to a file that was never written.

The server here is a real loopback socket that completes the WebSocket
handshake and then stays silent: no audio frames and no pong either.
"""

import base64
import hashlib
import socket
import threading

from voice.xunfei import xunfei_tts as xtts

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

#: Long enough for the patched ping to give up, short enough that a call which
#: hangs instead of failing does not stall the suite.
BUDGET = 20.0


class _SilentServer:
    """A WebSocket endpoint that shakes hands and then never answers."""

    def __init__(self, close_after_handshake=False):
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self.port = self._socket.getsockname()[1]
        self._close = close_after_handshake
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/tts"

    def _serve(self):
        conn, _ = self._socket.accept()
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = conn.recv(4096)
            if not chunk:
                return
            request += chunk
        key = ""
        for line in request.decode("utf-8", "replace").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        if self._close:
            conn.close()
            return
        threading.Event().wait(120)  # silent, and never pongs


def _a_call(monkeypatch, tmp_path, server):
    """Run ``xunfei_tts`` against ``server`` on a thread, and report what it did."""
    monkeypatch.setattr(xtts.Ws_Param, "create_url", lambda self: server.url)
    # ``raising=False``: a tree without the constants is exactly the bug being
    # pinned, so the call has to be left unbounded there rather than erroring on
    # a missing attribute.
    monkeypatch.setattr(xtts, "WS_PING_INTERVAL", 2, raising=False)
    monkeypatch.setattr(xtts, "WS_PING_TIMEOUT", 1, raising=False)

    out_path = str(tmp_path / "reply.mp3")
    outcome = {}

    def call():
        try:
            outcome["value"] = xtts.xunfei_tts("app", "key", "secret", {}, "hello", out_path)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            outcome["error"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(BUDGET)
    return worker, outcome, out_path


def test_a_provider_that_never_answers_does_not_hang_the_call(tmp_path, monkeypatch):
    worker, outcome, _ = _a_call(monkeypatch, tmp_path, _SilentServer())

    assert not worker.is_alive(), "a silent provider must not block the TTS call for good"
    assert isinstance(outcome.get("error"), RuntimeError), (
        "the caller has to be told the stream failed instead of getting a file "
        "that was never written"
    )


def test_a_stream_that_ends_cleanly_still_returns_the_output_file(tmp_path, monkeypatch):
    worker, outcome, out_path = _a_call(monkeypatch, tmp_path, _SilentServer(close_after_handshake=True))

    assert not worker.is_alive()
    assert outcome.get("value", out_path) == out_path
