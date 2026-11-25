"""Exercise Xunfei ASR result handling without a network connection."""

import importlib.util
import io
import json
from pathlib import Path
import sys
from threading import Event
from types import ModuleType
import wave

import pytest


@pytest.fixture
def asr(monkeypatch):
    monkeypatch.setitem(sys.modules, "websocket", ModuleType("websocket"))
    path = Path(__file__).resolve().parents[1] / "voice" / "xunfei" / "xunfei_asr.py"
    spec = importlib.util.spec_from_file_location("xunfei_asr_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.whole_dict = {}
    return module


def test_successive_dynamic_corrections_replace_previous_text(asr):
    asr.whole_dict = {1: "old1", 2: "old2"}

    asr.on_message(None, json.dumps({
        "code": 0, "sid": "t", "data": {"result": {
            "sn": 3, "rg": [1, 2], "ws": [{"cw": [{"w": "draft"}]}],
        }},
    }))
    asr.on_message(None, json.dumps({
        "code": 0, "sid": "t", "data": {"result": {
            "sn": 4, "rg": [3, 3], "ws": [{"cw": [{"w": "final"}]}],
        }},
    }))

    assert "".join(asr.whole_dict[sn] for sn in sorted(asr.whole_dict)) == "final"
    assert asr.whole_dict == {4: "final"}


def test_result_without_correction_is_stored_under_its_sequence_number(asr):
    asr.on_message(None, json.dumps({
        "code": 0, "sid": "t", "data": {"result": {
            "sn": 7, "ws": [{"cw": [{"w": "hello"}]}],
        }},
    }))

    assert asr.whole_dict == {7: "hello"}


@pytest.mark.parametrize("final_text", ["last words", None])
def test_asr_waits_for_final_result_with_a_timeout(asr, monkeypatch, final_text):
    sent_last_frame = Event()
    closed = Event()

    class FakeWebSocketApp:
        def __init__(self, url, on_message, on_error, on_close):
            self.on_message = on_message
            self.on_close = on_close

        def send(self, message):
            if json.loads(message)["data"]["status"] == 2:
                sent_last_frame.set()

        def close(self):
            closed.set()

        def run_forever(self, **kwargs):
            self.on_open(self)
            assert sent_last_frame.wait(2)
            self.on_message(self, json.dumps({
                "code": 0, "sid": "t", "data": {"status": 1, "result": {
                    "sn": 1, "ws": [{"cw": [{"w": "first words"}]}],
                }},
            }))
            if final_text is not None and not closed.wait(1.25):
                self.on_message(self, json.dumps({
                    "code": 0, "sid": "t", "data": {"status": 2, "result": {
                        "sn": 2, "ws": [{"cw": [{"w": final_text}]}],
                    }},
                }))
            assert closed.wait(2), "WebSocket did not close"
            self.on_close(self, None, None)

    monkeypatch.setattr(asr.websocket, "WebSocketApp", FakeWebSocketApp, raising=False)
    monkeypatch.setattr(asr.websocket, "enableTrace", lambda _: None, raising=False)
    if final_text is None:
        monkeypatch.setattr(asr, "FINAL_RESULT_TIMEOUT", 0.1, raising=False)

    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 160)
    audio.seek(0)

    expected = "first wordslast words" if final_text is not None else "first words"
    assert asr.xunfei_asr("app", "secret", "key", {}, audio) == expected
