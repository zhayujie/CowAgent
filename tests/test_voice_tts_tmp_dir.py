"""Synthesized TTS must land in the agent's managed tmp dir, not a CWD ``tmp/``.

``common/tmp_dir.py`` states the rule and even names the artifact: it resolves
"under the routed Agent's workspace rather than a CWD-relative ``./tmp``, which
is unreliable for the packaged desktop app where CWD is undefined" -- and its
docstring calls out "e.g. synthesized voice". Ten voice backends call
``TmpDir().path()``; these built ``"tmp/" + <timestamp><rand>`` by hand instead,
so the file landed in whatever directory the process happened to be started
from, and three of them did not even create that directory -- ``open()`` raised,
the outer ``except`` swallowed it, and the user just got
"遇到了一点小问题，请稍后再问" back.

The last test is the source guard the sibling channel fixes use: no backend in
``voice/`` may build a ``"tmp/"`` literal again.
"""

import ast
import base64
from pathlib import Path
from unittest.mock import Mock, patch

from bridge.reply import ReplyType
from common import state_dir
from voice.linkai import linkai_voice
from voice.mimo import mimo_voice
from voice.minimax import minimax_voice
from voice.openai import openai_voice
from voice.zhipuai import zhipuai_voice

VOICE_DIR = Path(__file__).resolve().parent.parent / "voice"


def _assert_managed(reply):
    """The backend must have written its audio inside the routed Agent's tmp dir."""
    assert reply.content, "the backend must return an audio path"
    assert Path(reply.content).resolve().parent == state_dir.tmp_dir().resolve(), reply.content


def test_linkai_tts_lands_in_the_managed_tmp_dir():
    response = Mock(status_code=200, content=b"mp3-bytes")
    with patch.object(linkai_voice, "conf", lambda: {"linkai_api_key": "k"}), \
            patch.object(linkai_voice, "apply_client_source", lambda h: h), \
            patch.object(linkai_voice, "apply_cloud_user", lambda h: h), \
            patch.object(linkai_voice.requests, "post", return_value=response):
        reply = linkai_voice.LinkAIVoice().textToVoice("你好")

    assert reply.type == ReplyType.VOICE
    _assert_managed(reply)


def test_openai_tts_lands_in_the_managed_tmp_dir():
    response = Mock(content=b"mp3-bytes")
    with patch.object(openai_voice, "conf", lambda: {"open_ai_api_key": "k"}), \
            patch.object(openai_voice.requests, "post", return_value=response):
        reply = openai_voice.OpenaiVoice().textToVoice("你好")

    assert reply.type == ReplyType.VOICE
    _assert_managed(reply)


def test_mimo_tts_lands_in_the_managed_tmp_dir():
    body = {"choices": [{"message": {"audio": {"data": base64.b64encode(b"wav").decode()}}}]}
    response = Mock(status_code=200, json=lambda: body)
    with patch.object(mimo_voice, "conf", lambda: {"mimo_api_key": "k"}), \
            patch.object(mimo_voice.requests, "post", return_value=response):
        reply = mimo_voice.MimoVoice().textToVoice("你好")

    assert reply.type == ReplyType.VOICE
    _assert_managed(reply)


def test_minimax_tts_lands_in_the_managed_tmp_dir():
    chunk = b'data: {"data": {"audio": "%s"}}' % b"mp3".hex().encode()
    response = Mock(raise_for_status=lambda: None, headers={}, iter_lines=lambda: [chunk])
    with patch.object(minimax_voice, "conf", lambda: {"minimax_api_key": "k"}), \
            patch.object(minimax_voice.requests, "post", return_value=response):
        reply = minimax_voice.MinimaxVoice().textToVoice("你好")

    assert reply.type == ReplyType.VOICE
    _assert_managed(reply)


def test_zhipuai_tts_lands_in_the_managed_tmp_dir():
    response = Mock(status_code=200, headers={"Content-Type": "audio/wav"}, content=b"RIFFwav")
    with patch.object(zhipuai_voice, "conf", lambda: {"zhipu_ai_api_key": "k"}), \
            patch.object(zhipuai_voice.requests, "post", return_value=response):
        reply = zhipuai_voice.ZhipuAIVoice().textToVoice("你好")

    assert reply.type == ReplyType.VOICE
    _assert_managed(reply)


def test_no_voice_backend_builds_a_cwd_relative_tmp_path():
    """Guards against a ``"tmp/"`` literal drifting back into any backend.

    Commented-out references (``voice/xunfei/xunfei_voice.py``) are not string
    constants, so they do not trip this.
    """
    offenders = {}
    for source_file in sorted(VOICE_DIR.rglob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        hits = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("tmp/")
        ]
        if hits:
            offenders[source_file.name] = hits
    assert offenders == {}
