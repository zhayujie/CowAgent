# encoding:utf-8
"""Bounded-download guard for Baidu's long-text synthesis.

Once the polling loop reports success, ``_long_text_synthesis`` downloads
``audio_address`` -- a URL that comes back from the vendor's task API -- with
``requests.get(...).content`` and writes it out. Nothing capped either the read
or the write, so an endless or multi-gigabyte body was buffered whole and
landed in the managed tmp dir before anything could object.

``baidu-aip`` is not in ``requirements.txt``, so the SDK is stubbed before the
module under test is imported (the same way ``sys.modules["linkai"]`` is
stubbed elsewhere in this suite).
"""
import sys
import types
from unittest.mock import MagicMock, patch

import requests

if "aip" not in sys.modules:
    _aip = types.ModuleType("aip")
    _aip.AipSpeech = object
    sys.modules["aip"] = _aip

from bridge.reply import ReplyType  # noqa: E402
from common.media_download import MAX_FILE_BYTES  # noqa: E402
from voice.baidu.baidu_voice import BaiduVoice  # noqa: E402
from tests.sleep_stub import stub_sleep  # noqa: E402


def _voice():
    """Build a BaiduVoice without ``__init__``: it reads -- or creates -- the
    provider's ``config.json`` inside the repo."""
    voice = BaiduVoice.__new__(BaiduVoice)
    voice.lang, voice.spd, voice.pit, voice.vol = "zh", 5, 5, 5
    voice._get_access_token = lambda: "token"
    return voice


def test_long_text_synthesis_rejects_oversized_audio(monkeypatch):
    created = MagicMock()
    created.json.return_value = {"task_id": "task-1"}
    finished = MagicMock()
    finished.json.return_value = {
        "tasks_info": [{
            "task_status": "Success",
            "task_result": {"audio_address": "http://example.test/audio.mp3"},
        }]
    }

    audio = MagicMock()
    audio.content = b"mp3"  # only the pre-fix non-streaming path reads this
    audio.headers = {}
    audio.raise_for_status.return_value = None
    audio.close.return_value = None
    # Enough 64 KiB chunks to cross the cap.
    chunks = MAX_FILE_BYTES // (64 * 1024) + 10
    audio.iter_content.return_value = [b"x" * (64 * 1024)] * chunks

    def _post(url, **kwargs):
        return finished if "query" in url else created

    stub_sleep(monkeypatch)
    with patch("voice.baidu.baidu_voice.requests.post", side_effect=_post), \
            patch.object(requests, "get", return_value=audio):
        reply = _voice()._long_text_synthesis("你好")

    assert reply.type == ReplyType.ERROR
