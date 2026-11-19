# encoding:utf-8
"""voiceToText's error reply must carry the exception, not a literal {0}."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.xunfei import xunfei_voice as xv


def test_asr_failure_reply_contains_the_cause():
    voice = xv.XunfeiVoice.__new__(xv.XunfeiVoice)
    voice.APPID, voice.APIKey, voice.APISecret = "appid", "apikey", "apisecret"
    voice.BusinessArgsASR = {"domain": "iat"}

    with patch.object(xv, "TmpDir") as tmp_dir, \
            patch.object(xv, "xunfei_asr", side_effect=OSError("websocket refused")):
        tmp_dir.return_value.path.return_value = os.path.join(os.getcwd(), "tmp")
        reply = voice.voiceToText(None)

    assert reply.type == ReplyType.ERROR
    assert "websocket refused" in reply.content
    assert "{0}" not in reply.content
