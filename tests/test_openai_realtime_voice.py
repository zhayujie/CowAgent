# encoding:utf-8
"""OpenAI speech goes through the Realtime API by default; transcription
defaults to gpt-transcribe. Both fall back to the legacy model only when the
user left the model unset."""

import base64
import json
import sys
import wave
from types import ModuleType, SimpleNamespace

import pytest

from bridge.reply import ReplyType
from voice.openai import openai_voice as module

PCM = b"\x01\x00\x02\x00" * 240


class FakeSocket:
    def __init__(self, events):
        self.events = [json.dumps(e) for e in events]
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        return self.events.pop(0)

    def close(self):
        self.closed = True


def _completed(*chunks):
    return [{"type": "session.updated"}] + [
        {"type": "response.output_audio.delta", "delta": base64.b64encode(c).decode()} for c in chunks
    ] + [{"type": "response.done", "response": {"status": "completed"}}]


@pytest.fixture
def env(monkeypatch, tmp_path):
    state = SimpleNamespace(conf={"open_ai_api_key": "sk-test"}, connects=[], posts=[],
                            socket=FakeSocket(_completed(PCM[:480], PCM[480:])), connect_error=None)

    def create_connection(url, header=None, timeout=None):
        state.connects.append({"url": url, "header": header, "timeout": timeout})
        if state.connect_error:
            raise state.connect_error
        return state.socket

    fake_ws = ModuleType("websocket")
    fake_ws.create_connection = create_connection
    monkeypatch.setitem(sys.modules, "websocket", fake_ws)
    monkeypatch.setattr(module, "conf", lambda: state.conf)

    def post(url, **kwargs):
        state.posts.append({"url": url, **kwargs})
        return SimpleNamespace(status_code=200, iter_content=lambda chunk_size=None: [b"mp3"],
                               headers={}, close=lambda: None, json=lambda: {"text": "hi"})

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module, "TmpDir", lambda: SimpleNamespace(path=lambda: str(tmp_path) + "/"))
    return state


def test_default_speech_uses_the_realtime_api(env):
    reply = module.OpenaiVoice().textToVoice("你好，世界")

    assert reply.type == ReplyType.VOICE
    assert env.posts == []
    connect = env.connects[0]
    assert connect["url"] == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"
    assert connect["header"] == ["Authorization: Bearer sk-test"]
    session, response = env.socket.sent
    assert session["type"] == "session.update"
    assert session["session"]["output_modalities"] == ["audio"]
    assert session["session"]["audio"]["output"]["voice"] == "marin"
    assert session["session"]["reasoning"] == {"effort": "minimal"}
    assert response["type"] == "response.create"
    assert response["response"]["conversation"] == "none"
    assert "<text>\n你好，世界\n</text>" in response["response"]["instructions"]
    assert env.socket.closed
    with wave.open(reply.content, "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.readframes(wav.getnframes()) == PCM


def test_a_voice_only_the_speech_endpoint_has_becomes_the_default(env):
    env.conf["tts_voice_id"] = "nova"
    module.OpenaiVoice().textToVoice("hi")
    assert env.socket.sent[0]["session"]["audio"]["output"]["voice"] == "marin"


def test_a_realtime_voice_is_kept(env):
    env.conf["tts_voice_id"] = "cedar"
    module.OpenaiVoice().textToVoice("hi")
    assert env.socket.sent[0]["session"]["audio"]["output"]["voice"] == "cedar"


@pytest.mark.parametrize("base, url", [
    ("https://gateway.example/v1/", "wss://gateway.example/v1/realtime?model=gpt-realtime-2.1-mini"),
    ("http://127.0.0.1:8000/v1", "ws://127.0.0.1:8000/v1/realtime?model=gpt-realtime-2.1-mini"),
])
def test_the_socket_url_follows_the_api_base(env, base, url):
    env.conf["open_ai_api_base"] = base
    module.OpenaiVoice().textToVoice("hi")
    assert env.connects[0]["url"] == url


def test_a_non_reasoning_realtime_model_gets_no_reasoning_setting(env):
    env.conf["text_to_voice_model"] = "gpt-realtime-1.5"
    module.OpenaiVoice().textToVoice("hi")
    assert "reasoning" not in env.socket.sent[0]["session"]


def test_the_default_falls_back_to_tts_1_when_realtime_fails(env):
    env.connect_error = OSError("Handshake status 404 Not Found")
    reply = module.OpenaiVoice().textToVoice("hi")

    assert reply.type == ReplyType.VOICE
    assert [p["url"] for p in env.posts] == ["https://api.openai.com/v1/audio/speech"]
    assert env.posts[0]["json"]["model"] == "tts-1"


@pytest.mark.parametrize("events", [
    [{"type": "error", "error": {"message": "Invalid model"}}],
    [{"type": "response.done", "response": {"status": "failed"}}],
    [{"type": "response.done", "response": {"status": "completed"}}],
])
def test_a_chosen_realtime_model_reports_its_failure(env, events):
    env.conf["text_to_voice_model"] = "gpt-realtime-2.1-mini"
    env.socket = FakeSocket(events)
    reply = module.OpenaiVoice().textToVoice("hi")

    assert reply.type == ReplyType.ERROR
    assert env.posts == []
    assert env.socket.closed


def test_a_legacy_model_never_opens_a_socket(env):
    env.conf["text_to_voice_model"] = "tts-1-hd"
    reply = module.OpenaiVoice().textToVoice("hi")

    assert reply.type == ReplyType.VOICE
    assert env.connects == []
    assert env.posts[0]["json"]["model"] == "tts-1-hd"


def _transcribe(env, tmp_path, monkeypatch, statuses):
    responses = iter(statuses)

    def post(url, **kwargs):
        env.posts.append({"url": url, **kwargs})
        status = next(responses)
        return SimpleNamespace(status_code=status, text="", json=lambda: {"text": "hi"} if status == 200 else {})

    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(module.requests, "post", post)
    return module.OpenaiVoice().voiceToText(str(audio))


def test_transcription_defaults_to_gpt_transcribe(env, tmp_path, monkeypatch):
    reply = _transcribe(env, tmp_path, monkeypatch, [200])
    assert reply.type == ReplyType.TEXT
    assert [p["data"]["model"] for p in env.posts] == ["gpt-transcribe"]


def test_a_rejected_default_retries_with_the_previous_model(env, tmp_path, monkeypatch):
    reply = _transcribe(env, tmp_path, monkeypatch, [404, 200])
    assert reply.type == ReplyType.TEXT
    assert [p["data"]["model"] for p in env.posts] == ["gpt-transcribe", "gpt-4o-mini-transcribe"]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_auth_quota_and_server_errors_are_not_retried(env, tmp_path, monkeypatch, status):
    reply = _transcribe(env, tmp_path, monkeypatch, [status])
    assert reply.type == ReplyType.ERROR
    assert len(env.posts) == 1


def test_a_chosen_transcription_model_is_not_replaced(env, tmp_path, monkeypatch):
    env.conf["voice_to_text_model"] = "whisper-1"
    reply = _transcribe(env, tmp_path, monkeypatch, [404])
    assert reply.type == ReplyType.ERROR
    assert [p["data"]["model"] for p in env.posts] == ["whisper-1"]
