"""A Xunfei TTS stream that delivers its last audio frame must succeed.

websocket-client calls ``on_close(ws, close_status_code, close_msg)``. A handler
that takes fewer arguments raises ``TypeError``, which the library passes to
``on_error``, and ``xunfei_tts`` then reports a failed stream.
"""

import base64
import hashlib
import json
import socket
import struct
import threading

from voice.xunfei import xunfei_tts as xtts

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_frame(conn):
    head = conn.recv(2)
    if len(head) < 2:
        return None, b""
    opcode = head[0] & 0x0F
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", conn.recv(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", conn.recv(8))[0]
    mask = conn.recv(4)
    data = b""
    while len(data) < length:
        data += conn.recv(length - len(data))
    return opcode, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def _send_frame(conn, opcode, payload):
    head = bytes([0x80 | opcode])
    if len(payload) < 126:
        head += bytes([len(payload)])
    else:
        head += bytes([126]) + struct.pack(">H", len(payload))
    conn.sendall(head + payload)


class _OneFrameServer:
    """Shakes hands, answers the text request with one final audio frame."""

    def __init__(self, audio):
        self._audio = audio
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self.port = self._socket.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self._socket.accept()
        request = b""
        while b"\r\n\r\n" not in request:
            request += conn.recv(4096)
        key = ""
        for line in request.decode().split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        conn.sendall((
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode())
        _recv_frame(conn)  # the text request
        _send_frame(conn, 0x1, json.dumps({
            "code": 0, "sid": "s", "message": "success",
            "data": {"audio": base64.b64encode(self._audio).decode(), "status": 2},
        }).encode())
        opcode, payload = _recv_frame(conn)
        if opcode == 0x8:
            _send_frame(conn, 0x8, payload)
        conn.close()


def test_completed_stream_returns_the_audio_file(tmp_path, monkeypatch):
    server = _OneFrameServer(b"ID3fake-mp3")
    monkeypatch.setattr(xtts.Ws_Param, "create_url", lambda self: f"ws://127.0.0.1:{server.port}/tts")
    out_path = str(tmp_path / "reply.mp3")

    assert xtts.xunfei_tts("app", "key", "secret", {}, "hello", out_path) == out_path
    with open(out_path, "rb") as f:
        assert f.read() == b"ID3fake-mp3"
