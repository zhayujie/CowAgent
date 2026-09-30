"""A TTS provider failure must answer with an ERROR reply, not a bare raise.

Every other provider under ``voice/`` turns a failure into
``Reply(ReplyType.ERROR, ...)``. Letting the raise travel instead reaches
``ChatChannel._fail_callback``, which only logs
(``channel/chat_channel.py:453``) -- and because this runs while a text reply is
being converted to voice, the user loses the text answer too.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.reply import Reply, ReplyType

# Both providers import an optional SDK at module scope. Neither SDK is needed
# to exercise the failure path, so they are stubbed just for this import and
# removed again right after.
_stubbed = []
if "edge_tts" not in sys.modules:
    _edge_tts = types.ModuleType("edge_tts")
    _edge_tts.Communicate = MagicMock()
    sys.modules["edge_tts"] = _edge_tts
    _stubbed.append("edge_tts")
if "elevenlabs" not in sys.modules:
    _elevenlabs = types.ModuleType("elevenlabs")
    _elevenlabs.save = MagicMock()
    _elevenlabs_client = types.ModuleType("elevenlabs.client")
    _elevenlabs_client.ElevenLabs = MagicMock()
    _elevenlabs.client = _elevenlabs_client
    sys.modules["elevenlabs"] = _elevenlabs
    sys.modules["elevenlabs.client"] = _elevenlabs_client
    _stubbed.extend(["elevenlabs", "elevenlabs.client"])

from voice.edge import edge_voice
from voice.elevent import elevent_voice

for _name in _stubbed:
    sys.modules.pop(_name, None)


def _raising(error):
    """A stand-in for ``gen_voice`` that fails the way the SDK does."""

    def _gen_voice(*args, **kwargs):
        raise error

    return _gen_voice


async def _silent_gen_voice(*args, **kwargs):
    return None


def test_a_failed_edge_synthesis_becomes_an_error_reply():
    voice = edge_voice.EdgeVoice()
    with patch.object(edge_voice.EdgeVoice, "gen_voice",
                      _raising(RuntimeError("No audio was received"))):
        reply = voice.textToVoice("你好")

    assert isinstance(reply, Reply)
    assert reply.type == ReplyType.ERROR


def test_a_failed_elevenlabs_synthesis_becomes_an_error_reply():
    voice = elevent_voice.ElevenLabsVoice()
    with patch.object(elevent_voice.client, "generate",
                      side_effect=RuntimeError("401 Unauthorized")):
        reply = voice.textToVoice("hello")

    assert reply.type == ReplyType.ERROR


def test_a_failed_elevenlabs_write_becomes_an_error_reply():
    voice = elevent_voice.ElevenLabsVoice()
    with patch.object(elevent_voice, "save", side_effect=OSError("No space left")):
        reply = voice.textToVoice("hello")

    assert reply.type == ReplyType.ERROR


def test_the_edge_failure_is_logged_rather_than_swallowed():
    voice = edge_voice.EdgeVoice()
    with patch.object(edge_voice.EdgeVoice, "gen_voice",
                      _raising(RuntimeError("connection reset"))), \
            patch.object(edge_voice.logger, "error") as log_error:
        voice.textToVoice("你好")

    assert log_error.called


def test_a_successful_edge_synthesis_still_returns_a_voice_reply():
    voice = edge_voice.EdgeVoice()
    with patch.object(edge_voice.EdgeVoice, "gen_voice", _silent_gen_voice):
        reply = voice.textToVoice("你好")

    assert reply.type == ReplyType.VOICE


def test_a_successful_elevenlabs_synthesis_still_returns_a_voice_reply():
    voice = elevent_voice.ElevenLabsVoice()
    with patch.object(elevent_voice, "save", MagicMock()):
        reply = voice.textToVoice("hello")

    assert reply.type == ReplyType.VOICE
