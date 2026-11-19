# encoding:utf-8
"""A WeCom / WeChatMP voice reply removes the source, the converted file and
every split segment -- on the success path and on the failure paths."""

import contextlib
import os
import sys
from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.wechat_kf import wechat_kf_channel as kf_module
from channel.wechatcom import wechatcomapp_channel as app_module
from channel.wechatmp import wechatmp_channel as mp_module


def _app_channel():
    cls = app_module.WechatComAppChannel.__wrapped__
    channel = cls.__new__(cls)
    channel.agent_id = "1000002"
    return channel


def _kf_channel():
    cls = kf_module.WechatKfChannel.__wrapped__
    channel = cls.__new__(cls)
    channel._send_voice = MagicMock()
    return channel


def _mp_channel(passive):
    cls = mp_module.WechatMPChannel.__wrapped__
    channel = cls.__new__(cls)
    channel.passive_reply = passive
    if passive:
        channel.cache_dict = defaultdict(list)
    return channel


def _mp_passive():
    return _mp_channel(passive=True)


def _mp_active():
    return _mp_channel(passive=False)


def _touch(src, dst):
    open(dst, "wb").close()


@contextlib.contextmanager
def _patched_voice(module, convert, **split_kwargs):
    """Patch the audio helpers a module actually imports.

    wechatmp only pulls any_to_mp3 out of voice.audio_convert, so any_to_amr
    is patched only where the module really has it.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(module, "split_audio", **split_kwargs))
        for name in ("any_to_amr", "any_to_mp3"):
            if hasattr(module, name):
                stack.enter_context(patch.object(module, name, convert))
        stack.enter_context(patch.object(module.time, "sleep"))
        yield


@pytest.mark.parametrize("module,make_channel", [(app_module, _app_channel), (kf_module, _kf_channel)])
@pytest.mark.parametrize("segment_count", [0, 3])
def test_voice_reply_leaves_no_audio_files(tmp_path, module, make_channel, segment_count):
    source = tmp_path / "reply.wav"
    source.write_bytes(b"audio")
    amr_file = str(tmp_path / "reply.amr")
    segments = [str(tmp_path / f"reply_{i}.amr") for i in range(segment_count)]
    for path in segments:
        open(path, "wb").close()
    files = segments or [amr_file]

    channel = make_channel()
    channel.client = MagicMock()
    channel.client.media.upload.return_value = {"media_id": "m"}
    context = Context()
    context["receiver"] = "user-1"
    context["external_userid"] = "user-1"
    context["open_kfid"] = "kf-1"

    with _patched_voice(module, _touch, return_value=(1000, files)):
        channel.send(Reply(ReplyType.VOICE, str(source)), context)

    assert channel.client.media.upload.call_count == len(files)
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("make_channel", [_mp_passive, _mp_active])
@pytest.mark.parametrize("segment_count", [0, 3])
@pytest.mark.parametrize("ext", [".wav", ".mp3"])
def test_wechatmp_voice_reply_leaves_no_audio_files(tmp_path, make_channel, segment_count, ext):
    source = tmp_path / ("reply" + ext)
    source.write_bytes(b"audio")
    converted = tmp_path / "reply.mp3"
    segments = [str(tmp_path / f"reply_{i}.amr") for i in range(segment_count)]
    for path in segments:
        open(path, "wb").close()
    # The active branch converts to mp3 before splitting; the passive one
    # splits the reply content itself.
    files = segments or [str(converted if make_channel is _mp_active else source)]

    channel = make_channel()
    channel.client = MagicMock()
    channel.client.material.add.return_value = {"media_id": "m"}
    channel.client.media.upload.return_value = {"media_id": "m"}
    context = Context()
    context["receiver"] = "user-1"
    context["external_userid"] = "user-1"
    context["open_kfid"] = "kf-1"

    with _patched_voice(mp_module, _touch, return_value=(1000, files)):
        channel.send(Reply(ReplyType.VOICE, str(source)), context)

    if make_channel is _mp_passive:
        assert channel.client.material.add.call_count == len(files)
    else:
        assert channel.client.media.upload.call_count == len(files)
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("module,make_channel", [
    (app_module, _app_channel),
    (kf_module, _kf_channel),
    (mp_module, _mp_passive),
    (mp_module, _mp_active),
])
def test_voice_reply_cleans_up_when_the_upload_fails(tmp_path, module, make_channel):
    source = tmp_path / "reply.wav"
    source.write_bytes(b"audio")
    segments = [str(tmp_path / f"reply_{i}.amr") for i in range(2)]
    for path in segments:
        open(path, "wb").close()
    files = segments

    channel = make_channel()
    channel.client = MagicMock()
    failure = module.WeChatClientException(-1, "upload refused")
    channel.client.media.upload.side_effect = failure
    channel.client.material.add.side_effect = failure
    context = Context()
    context["receiver"] = "user-1"
    context["external_userid"] = "user-1"
    context["open_kfid"] = "kf-1"

    with _patched_voice(module, _touch, return_value=(1000, files)):
        channel.send(Reply(ReplyType.VOICE, str(source)), context)

    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("module,make_channel", [
    (app_module, _app_channel),
    (kf_module, _kf_channel),
    (mp_module, _mp_passive),
    (mp_module, _mp_active),
])
def test_voice_reply_cleans_up_when_conversion_is_unavailable(tmp_path, module, make_channel):
    # pydub missing: the conversion raises ImportError before any segment
    # exists, but a partially written intermediate may already be on disk.
    source = tmp_path / "reply.wav"
    source.write_bytes(b"audio")

    channel = make_channel()
    channel.client = MagicMock()
    channel.client.media.upload.return_value = {"media_id": "m"}
    channel.client.material.add.return_value = {"media_id": "m"}
    context = Context()
    context["receiver"] = "user-1"
    context["external_userid"] = "user-1"
    context["open_kfid"] = "kf-1"

    def half_written_conversion(src, dst):
        open(dst, "wb").close()
        raise ImportError("pydub is required")

    with _patched_voice(module, half_written_conversion, side_effect=ImportError("pydub is required")):
        channel.send(Reply(ReplyType.VOICE, str(source)), context)

    assert os.listdir(tmp_path) == []
