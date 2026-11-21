# encoding:utf-8
"""
Unit tests for DeepSeek speech recognition / synthesis and voice auto-pick.

Covers:
  - voiceToText uploads a 16-bit PCM WAV as-is and returns the text
  - browser WebM recordings are repacked as Ogg Opus without ffmpeg/pydub,
    and Ogg Opus is uploaded as is
  - other formats are converted to WAV first, and the temp file is removed
  - HTTP errors / empty text become an ERROR reply
  - textToVoice posts text + voice_id and writes the streamed audio
  - an auto-picked DeepSeek ignores another vendor's tts_voice_id
  - a base configured without /v1 still reaches the /v1 tools endpoints
  - with only a DeepSeek key, both ASR and TTS auto-pick DeepSeek
  - the web console ASR / TTS cards offer DeepSeek
"""
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from common import state_dir
from voice.deepseek import deepseek_voice
from voice.deepseek.deepseek_voice import DeepSeekVoice


def _conf(**values):
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: values.get(key, default))
    return MagicMock(return_value=cfg)


def _response(status=200, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {}
    resp.text = str(body)
    return resp


def _write_wav(path, rate=16000, width=2):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * width * 160)


class TestDeepSeekVoiceToText(unittest.TestCase):
    def test_uploads_pcm16_wav_as_is(self):
        ok = _response(body={"request_id": "r", "text": " 上海天气 ", "duration_ms": 3200})
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "a.wav")
            _write_wav(audio)
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice, "_convert_to_wav") as conv, \
                    patch.object(deepseek_voice.requests, "post", return_value=ok) as post:
                reply = DeepSeekVoice().voiceToText(audio)

        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(reply.content, "上海天气")
        conv.assert_not_called()
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/v1/tools/asr")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer k")
        self.assertIn("file", post.call_args.kwargs["files"])
        self.assertIsNotNone(post.call_args.kwargs.get("timeout"))

    def test_converts_other_formats_and_cleans_up(self):
        ok = _response(body={"text": "hi"})
        produced = []

        def _fake_convert(src, dst):
            produced.append(dst)
            _write_wav(dst)

        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "a.amr")
            with open(audio, "wb") as f:
                f.write(b"#!AMR\n")
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice, "_convert_to_wav", side_effect=_fake_convert), \
                    patch.object(deepseek_voice.requests, "post", return_value=ok):
                reply = DeepSeekVoice().voiceToText(audio)

        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(len(produced), 1)
        self.assertFalse(os.path.exists(produced[0]))

    def test_webm_is_repacked_as_ogg_without_conversion(self):
        from tests.test_webm_opus import _PACKETS, _webm

        sent = {}

        def _post(url, headers=None, files=None, timeout=None):
            name, fh, mime = files["file"]
            sent.update(path=fh.name, mime=mime, head=fh.read(4))
            return _response(body={"text": "hi"})

        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "voice_input.webm")
            with open(audio, "wb") as f:
                f.write(_webm(_PACKETS))
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice, "_convert_to_wav") as conv, \
                    patch.object(deepseek_voice.requests, "post", side_effect=_post):
                reply = DeepSeekVoice().voiceToText(audio)

        self.assertEqual(reply.type, ReplyType.TEXT)
        conv.assert_not_called()
        self.assertEqual(sent["mime"], "audio/ogg")
        self.assertEqual(sent["head"], b"OggS")
        self.assertFalse(os.path.exists(sent["path"]))

    def test_ogg_opus_is_uploaded_as_is(self):
        from tests.test_webm_opus import _PACKETS, _webm

        with tempfile.TemporaryDirectory() as tmp:
            src, audio = os.path.join(tmp, "a.webm"), os.path.join(tmp, "a.opus")
            with open(src, "wb") as f:
                f.write(_webm(_PACKETS))
            deepseek_voice.webm_opus.webm_to_ogg(src, audio)
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice, "_convert_to_wav") as conv, \
                    patch.object(deepseek_voice.requests, "post", return_value=_response(body={"text": "hi"})) as post:
                DeepSeekVoice().voiceToText(audio)
            self.assertTrue(os.path.exists(audio))

        conv.assert_not_called()
        name, _, mime = post.call_args.kwargs["files"]["file"]
        self.assertEqual((name, mime), ("a.opus", "audio/ogg"))

    def test_unrepackable_webm_falls_back_to_conversion(self):
        from tests.test_webm_opus import _PACKETS, _webm

        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "a.webm")
            with open(audio, "wb") as f:
                f.write(_webm(_PACKETS, codec=b"A_VORBIS"))
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice, "_convert_to_wav",
                                 side_effect=lambda src, dst: _write_wav(dst)) as conv, \
                    patch.object(deepseek_voice.requests, "post", return_value=_response(body={"text": "x"})) as post:
                reply = DeepSeekVoice().voiceToText(audio)

        self.assertEqual(reply.type, ReplyType.TEXT)
        conv.assert_called_once()
        self.assertEqual(post.call_args.kwargs["files"]["file"][2], "audio/wav")

    def test_unsupported_wav_is_converted(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "a.wav")
            _write_wav(audio, rate=11025)
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice, "_convert_to_wav",
                                 side_effect=lambda src, dst: _write_wav(dst)) as conv, \
                    patch.object(deepseek_voice.requests, "post", return_value=_response(body={"text": "x"})):
                DeepSeekVoice().voiceToText(audio)
        conv.assert_called_once()

    def test_http_error_becomes_error_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "a.wav")
            _write_wav(audio)
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice.requests, "post", return_value=_response(413, {"error": "too big"})):
                reply = DeepSeekVoice().voiceToText(audio)
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_empty_text_becomes_error_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "a.wav")
            _write_wav(audio)
            with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                    patch.object(deepseek_voice.requests, "post", return_value=_response(body={"text": ""})):
                reply = DeepSeekVoice().voiceToText(audio)
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_missing_key_skips_request(self):
        with patch.object(deepseek_voice, "conf", _conf()), \
                patch.object(deepseek_voice.requests, "post") as post:
            reply = DeepSeekVoice().voiceToText("/nonexistent.wav")
        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()


class TestDeepSeekTextToVoice(unittest.TestCase):
    def _tts(self, **cfg):
        response = Mock(status_code=200, headers={"Content-Type": "audio/wav"},
                        iter_content=lambda chunk_size: [b"RIFFwav"])
        with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k", **cfg)), \
                patch.object(deepseek_voice.requests, "post", return_value=response) as post:
            reply = DeepSeekVoice().textToVoice("你好")
        return reply, post

    def test_posts_text_and_writes_audio(self):
        reply, post = self._tts(text_to_voice="deepseek", tts_voice_id="tide")
        self.assertEqual(reply.type, ReplyType.VOICE)
        self.assertEqual(Path(reply.content).resolve().parent, state_dir.tmp_dir().resolve())
        self.assertEqual(Path(reply.content).read_bytes(), b"RIFFwav")
        os.remove(reply.content)
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/v1/tools/tts")
        self.assertEqual(post.call_args.kwargs["json"],
                         {"text": "你好", "voice_id": "tide", "format": "wav"})
        self.assertTrue(post.call_args.kwargs["stream"])

    def test_streamed_wav_header_is_fixed(self):
        pcm = b"\x01\x00" * 2400
        streamed = (b"RIFF\xff\xff\xff\xffWAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
                    b"\xc0]\x00\x00\x80\xbb\x00\x00\x02\x00\x10\x00data\xff\xff\xff\xff" + pcm)
        response = Mock(status_code=200, headers={}, iter_content=lambda chunk_size: [streamed])
        with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                patch.object(deepseek_voice.requests, "post", return_value=response):
            reply = DeepSeekVoice().textToVoice("你好")
        with wave.open(reply.content, "rb") as w:
            self.assertEqual(w.getnframes(), 2400)
            self.assertEqual(w.readframes(w.getnframes()), pcm)
        os.remove(reply.content)

    def test_auto_picked_ignores_foreign_voice(self):
        reply, post = self._tts(text_to_voice="", tts_voice_id="alloy")
        os.remove(reply.content)
        self.assertEqual(post.call_args.kwargs["json"]["voice_id"], "stella")

    def test_base_without_v1_reaches_tools_endpoint(self):
        reply, post = self._tts(deepseek_api_base="https://api.deepseek.com/")
        os.remove(reply.content)
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/v1/tools/tts")

    def test_http_error_becomes_error_reply(self):
        response = Mock(status_code=400, text="Content Exists Risk")
        with patch.object(deepseek_voice, "conf", _conf(deepseek_api_key="k")), \
                patch.object(deepseek_voice.requests, "post", return_value=response):
            reply = DeepSeekVoice().textToVoice("你好")
        self.assertEqual(reply.type, ReplyType.ERROR)


def _bridge_class():
    from bridge.bridge import Bridge

    return Bridge.__wrapped__


class TestVoiceAutoPick(unittest.TestCase):
    def test_deepseek_key_alone_enables_asr_and_tts(self):
        Bridge = _bridge_class()
        with patch("bridge.bridge.conf", _conf(deepseek_api_key="sk-x")):
            self.assertEqual(Bridge._auto_pick_voice_to_text(), "deepseek")
            self.assertEqual(Bridge._auto_pick_text_to_voice(), "deepseek")

    def test_fallbacks_when_nothing_configured(self):
        Bridge = _bridge_class()
        with patch("bridge.bridge.conf", _conf()):
            self.assertEqual(Bridge._auto_pick_voice_to_text(), "openai")
            self.assertEqual(Bridge._auto_pick_text_to_voice(), "google")

    def test_tts_auto_pick_without_deepseek(self):
        Bridge = _bridge_class()
        with patch("bridge.bridge.conf", _conf(minimax_api_key="m", mimo_api_key="x")):
            self.assertEqual(Bridge._auto_pick_text_to_voice(), "minimax")


class TestDeepSeekVoiceCapability(unittest.TestCase):
    def test_cards_suggest_deepseek(self):
        from channel.web.api.models import ModelsHandler

        cfg = {"deepseek_api_key": "sk-x", "open_ai_api_key": "sk-y"}
        asr = ModelsHandler._asr_capability(cfg)
        tts = ModelsHandler._tts_capability(cfg)
        self.assertEqual(asr["suggested_provider"], "deepseek")
        self.assertEqual(tts["suggested_provider"], "deepseek")
        self.assertIn("deepseek", asr["provider_models"])
        voices = [v["value"] for v in tts["provider_voices"]["deepseek"]]
        self.assertEqual(voices, ["stella", "tide"])


if __name__ == "__main__":
    unittest.main()
