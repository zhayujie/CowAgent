# encoding:utf-8
"""The inbound voice branch must not leave recordings behind in the tmp dir.

_generate_reply converts the inbound audio to wav next to it, then deletes the
temporary files. Two things leaked:

* On a conversion failure the code reassigned ``wav_path = file_path`` before
  the cleanup ran, so the output the failing encoder had already created was no
  longer named anywhere and stayed in the tmp dir for good. pydub opens the
  destination ``wb+`` before it runs ffmpeg, so an encoder that exits nonzero
  leaves an empty file at that path.
* The two removals shared one ``try``, so a failure on the first one skipped
  the second. That one strands the converted wav, which does hold the user's
  own recording.
"""
import os

import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel import chat_channel as mod


class _PassThroughPlugins:
    def emit_event(self, e_context):
        return e_context


class _FakeMsg:
    def prepare(self):
        pass


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setattr(mod, "PluginManager", _PassThroughPlugins)
    # Skip __init__: it starts the consumer thread, which this test does not need.
    ch = mod.ChatChannel.__new__(mod.ChatChannel)
    ch.NOT_SUPPORT_REPLYTYPE = []
    ch.stt_paths = []

    def build_voice_to_text(_self, path):
        ch.stt_paths.append(path)
        return Reply(ReplyType.TEXT, "transcript")

    monkeypatch.setattr(mod.Channel, "build_voice_to_text", build_voice_to_text)
    # The transcript would otherwise be composed into a follow-up text turn.
    monkeypatch.setattr(mod.ChatChannel, "_compose_context", lambda self, *a, **k: None)
    return ch


def _voice_context(tmp_path, name="wx_123.silk"):
    src = tmp_path / name
    src.write_bytes(b"silk-audio")
    return Context(ContextType.VOICE, str(src), kwargs={"msg": _FakeMsg()})


def test_a_failed_conversion_leaves_no_orphaned_output(channel, monkeypatch, tmp_path):
    def failing_any_to_wav(any_path, wav_path):
        # pydub opens the destination wb+ before it runs ffmpeg, so an encoder
        # that exits nonzero leaves the (empty) file behind. Stubbed here
        # because pydub is an optional dependency and is absent in CI.
        with open(wav_path, "wb"):
            pass
        raise RuntimeError("ffmpeg: Encoder not found")

    monkeypatch.setattr(mod, "any_to_wav", failing_any_to_wav)

    context = _voice_context(tmp_path)
    channel._generate_reply(context)

    # The fallback still transcribes the raw audio, as before.
    assert channel.stt_paths == [context.content]
    assert os.listdir(tmp_path) == []


def test_a_failed_source_removal_still_removes_the_converted_wav(channel, monkeypatch, tmp_path):
    context = _voice_context(tmp_path)
    source = context.content

    def converting_any_to_wav(any_path, wav_path):
        with open(wav_path, "wb") as f:
            f.write(b"RIFF")

    monkeypatch.setattr(mod, "any_to_wav", converting_any_to_wav)

    real_remove = os.remove

    def remove(path, *args, **kwargs):
        if path == source:
            raise PermissionError(path)
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(mod.os, "remove", remove)

    channel._generate_reply(context)

    # The source could not be removed, but that must not strand the wav too.
    assert os.listdir(tmp_path) == [os.path.basename(source)]


def test_an_inbound_wav_is_removed_exactly_once(channel, monkeypatch, tmp_path):
    """file_path and wav_path are the same name here; cleanup must not double-remove."""
    context = _voice_context(tmp_path, name="wx_123.wav")

    def same_file(any_path, wav_path):
        raise OSError("are the same file")

    monkeypatch.setattr(mod, "any_to_wav", same_file)
    removed = []
    real_remove = os.remove

    def remove(path, *args, **kwargs):
        removed.append(path)
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(mod.os, "remove", remove)

    channel._generate_reply(context)

    assert removed == [context.content]
    assert os.listdir(tmp_path) == []
