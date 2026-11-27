"""Two Xunfei ASR or TTS calls at once must each work on their own input and output."""

import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
from threading import Barrier, BrokenBarrierError, Event, Thread, Timer
from types import ModuleType
import wave

from tests.sleep_stub import stub_sleep


def _load(monkeypatch, name):
    monkeypatch.setitem(sys.modules, "websocket", ModuleType("websocket"))
    path = Path(__file__).resolve().parents[1] / "voice" / "xunfei" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_concurrent_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.websocket, "enableTrace", lambda _: None, raising=False)
    return module


def _run_two_at_once(call):
    results = {}
    threads = [Thread(target=lambda n=n: results.__setitem__(n, call(n))) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return results


def _wav(fill: bytes) -> io.BytesIO:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(fill * 320)
    audio.seek(0)
    return audio


def test_concurrent_asr_calls_keep_their_own_audio_and_transcript(monkeypatch):
    asr = _load(monkeypatch, "xunfei_asr")
    # Both handshakes are in flight before either socket opens, as when two users send a
    # voice message at the same moment. A serialised call times out here and goes on alone.
    handshakes = Barrier(2, timeout=0.5)

    class FakeWebSocketApp:
        def __init__(self, url, on_message, on_error, on_close):
            self.on_message = on_message
            self.on_close = on_close
            self.audio = b""
            self.closed = Event()

        def send(self, message):
            data = json.loads(message)["data"]
            self.audio += base64.b64decode(data["audio"])
            if data["status"] == 2:
                # The "recognised text" is the letter the audio was filled with.
                self.on_message(self, json.dumps({
                    "code": 0, "sid": "t", "data": {"status": 2, "result": {
                        "sn": 1, "ws": [{"cw": [{"w": self.audio[:1].decode()}]}],
                    }},
                }))

        def close(self):
            self.closed.set()

        def run_forever(self, **kwargs):
            try:
                handshakes.wait()
            except BrokenBarrierError:
                pass
            self.on_open(self)
            assert self.closed.wait(5), "WebSocket did not close"
            self.on_close(self, None, None)

    monkeypatch.setattr(asr.websocket, "WebSocketApp", FakeWebSocketApp, raising=False)
    stub_sleep(monkeypatch)

    results = _run_two_at_once(lambda n: asr.xunfei_asr("app", "secret", "key", {}, _wav(n.encode())))

    assert results == {"a": "a", "b": "b"}


def test_concurrent_tts_calls_write_their_own_text_to_their_own_file(monkeypatch, tmp_path):
    tts = _load(monkeypatch, "xunfei_tts")
    handshakes = Barrier(2, timeout=0.5)

    class FakeWebSocketApp:
        def __init__(self, url, on_message, on_error, on_close):
            self.on_message = on_message
            self.on_close = on_close
            self.closed = Event()

        def send(self, message):
            # The "synthesised audio" is the text it was asked to speak. It arrives after
            # on_open has cleared the output file, as from the real server.
            text = base64.b64decode(json.loads(message)["data"]["text"])
            Timer(0.1, self.on_message, (self, json.dumps({
                "code": 0, "sid": "t",
                "data": {"status": 2, "audio": base64.b64encode(text).decode()},
            }))).start()

        def close(self):
            self.closed.set()

        def run_forever(self, **kwargs):
            try:
                handshakes.wait()
            except BrokenBarrierError:
                pass
            self.on_open(self)
            assert self.closed.wait(5), "WebSocket did not close"
            self.on_close(self, None, None)

    monkeypatch.setattr(tts.websocket, "WebSocketApp", FakeWebSocketApp, raising=False)

    results = _run_two_at_once(
        lambda n: tts.xunfei_tts("app", "key", "secret", {}, f"text {n}", str(tmp_path / f"{n}.mp3"))
    )

    assert results == {"a": str(tmp_path / "a.mp3"), "b": str(tmp_path / "b.mp3")}
    assert (tmp_path / "a.mp3").read_bytes() == b"text a"
    assert (tmp_path / "b.mp3").read_bytes() == b"text b"
