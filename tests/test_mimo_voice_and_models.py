# encoding:utf-8
"""
Unit tests for Xiaomi MiMo speech recognition and model id handling.

Covers:
  - voiceToText posts a base64 data URI to /chat/completions and returns the text
  - non mp3 / wav input is converted to mp3 before upload
  - HTTP / API errors become an ERROR reply
  - retired chat model ids map onto their V2.6 replacements
  - the web console ASR card offers MiMo with its preset model
"""
import base64
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.mimo.mimo_voice import MimoVoice


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


class TestMimoVoiceToText(unittest.TestCase):
    def _write(self, tmp, name, data=b"RIFFfake"):
        path = os.path.join(tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_posts_data_uri_and_returns_text(self):
        ok = _response(body={"choices": [{"message": {"content": " 你好 "}}]})
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._write(tmp, "a.wav")
            with patch("voice.mimo.mimo_voice.conf", _conf(mimo_api_key="k")), \
                    patch("voice.mimo.mimo_voice.requests.post", return_value=ok) as post:
                reply = MimoVoice().voiceToText(audio)

        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(reply.content, "你好")
        url = post.call_args.args[0]
        self.assertEqual(url, "https://api.xiaomimimo.com/v1/chat/completions")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "mimo-v2.5-asr")
        part = payload["messages"][0]["content"][0]
        self.assertEqual(part["type"], "input_audio")
        expected = "data:audio/wav;base64," + base64.b64encode(b"RIFFfake").decode()
        self.assertEqual(part["input_audio"]["data"], expected)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer k")
        self.assertIsNotNone(post.call_args.kwargs.get("timeout"))

    def test_converts_unsupported_format_to_mp3(self):
        ok = _response(body={"choices": [{"message": {"content": "hi"}}]})

        def _fake_convert(src, dst):
            with open(dst, "wb") as f:
                f.write(b"ID3fake")

        with tempfile.TemporaryDirectory() as tmp:
            audio = self._write(tmp, "a.amr")
            with patch("voice.mimo.mimo_voice.conf", _conf(mimo_api_key="k")), \
                    patch("voice.mimo.mimo_voice.audio_convert.any_to_mp3", side_effect=_fake_convert) as conv, \
                    patch("voice.mimo.mimo_voice.requests.post", return_value=ok) as post:
                reply = MimoVoice().voiceToText(audio)

        self.assertEqual(reply.type, ReplyType.TEXT)
        conv.assert_called_once()
        data = post.call_args.kwargs["json"]["messages"][0]["content"][0]["input_audio"]["data"]
        self.assertTrue(data.startswith("data:audio/mpeg;base64,"))

    def test_http_error_becomes_error_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._write(tmp, "a.mp3")
            with patch("voice.mimo.mimo_voice.conf", _conf(mimo_api_key="k")), \
                    patch("voice.mimo.mimo_voice.requests.post", return_value=_response(401, {"error": "bad key"})):
                reply = MimoVoice().voiceToText(audio)
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_api_error_body_becomes_error_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._write(tmp, "a.mp3")
            with patch("voice.mimo.mimo_voice.conf", _conf(mimo_api_key="k")), \
                    patch("voice.mimo.mimo_voice.requests.post", return_value=_response(200, {"error": {"message": "x"}})):
                reply = MimoVoice().voiceToText(audio)
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_missing_key_skips_request(self):
        with patch("voice.mimo.mimo_voice.conf", _conf()), \
                patch("voice.mimo.mimo_voice.requests.post") as post:
            reply = MimoVoice().voiceToText("/nonexistent.wav")
        self.assertEqual(reply.type, ReplyType.ERROR)
        post.assert_not_called()


class TestMimoModelResolution(unittest.TestCase):
    def test_retired_ids_map_to_v26(self):
        from models.mimo.mimo_bot import resolve_model

        self.assertEqual(resolve_model("mimo-v2.5-pro"), "mimo-v2.6-pro")
        self.assertEqual(resolve_model("MiMo-V2.5-Pro"), "mimo-v2.6-pro")
        self.assertEqual(resolve_model("mimo-v2.5"), "mimo-v2.6-flash")
        self.assertEqual(resolve_model("mimo-v2-pro"), "mimo-v2.6-pro")
        self.assertEqual(resolve_model("mimo-v2-omni"), "mimo-v2.6-flash")
        self.assertEqual(resolve_model("mimo-v2-flash"), "mimo-v2.6-flash")

    def test_current_and_empty_ids(self):
        from models.mimo.mimo_bot import resolve_model

        self.assertEqual(resolve_model("mimo-v2.6-flash"), "mimo-v2.6-flash")
        self.assertEqual(resolve_model(""), "mimo-v2.6-pro")
        self.assertEqual(resolve_model(None), "mimo-v2.6-pro")


class TestMimoAsrCapability(unittest.TestCase):
    def test_asr_card_offers_mimo(self):
        from channel.web.api.models import ModelsHandler

        cap = ModelsHandler._asr_capability({
            "voice_to_text": "mimo",
            "voice_to_text_model": "mimo-v2.5-asr",
        })
        self.assertEqual(cap["current_provider"], "mimo")
        self.assertIn("mimo", cap["providers"])
        models = [m["value"] if isinstance(m, dict) else m for m in cap["provider_models"]["mimo"]]
        self.assertIn("mimo-v2.5-asr", models)


if __name__ == "__main__":
    unittest.main()
