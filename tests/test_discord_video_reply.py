# encoding:utf-8
"""Discord outbound replies that carry a local video.

``ChatChannel`` extracts a video the agent produced and hands it over as
``Reply(ReplyType.VIDEO, "file://" + path)`` (``channel/chat_channel.py``). The
QQ, wechatcom, weixin and wecom_bot channels all match ``ReplyType.VIDEO`` and
upload the file, but ``DiscordChannel._async_send`` covers TEXT/INFO/ERROR,
IMAGE, IMAGE_URL and VOICE/FILE only, so a VIDEO reply fell through to the
plain-text fallback: the user got the literal ``file:///...`` path as a message
bubble and the video itself was never uploaded.
"""
import asyncio
import sys
import types

from bridge.reply import Reply, ReplyType


class _RecordingChannel:
    def __init__(self):
        self.sends = []

    async def send(self, *args, **kwargs):
        self.sends.append((args, kwargs))


class _FakeFile:
    def __init__(self, fp, filename=None):
        self.fp = fp
        self.filename = filename


def _channel(monkeypatch):
    """A DiscordChannel holding only what _async_send reads, with discord stubbed."""
    from channel.discord import discord_channel as mod

    discord = types.ModuleType("discord")
    discord.File = _FakeFile
    monkeypatch.setitem(sys.modules, "discord", discord)

    target = _RecordingChannel()
    cls = mod.DiscordChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._client = types.SimpleNamespace(get_channel=lambda cid: target)
    return ch, target


def test_local_video_is_uploaded_as_a_file(monkeypatch):
    ch, target = _channel(monkeypatch)
    asyncio.run(ch._async_send(Reply(ReplyType.VIDEO, "file:///srv/cow/tmp/clip.mp4"), 7))

    assert len(target.sends) == 1, target.sends
    args, kwargs = target.sends[0]
    file = kwargs.get("file")
    assert isinstance(file, _FakeFile), f"video posted as a text bubble: {args} {kwargs}"
    assert file.fp == "/srv/cow/tmp/clip.mp4"
    assert not args, f"the local path must not be posted as text: {args}"


def test_remote_video_url_is_still_posted_as_text(monkeypatch):
    """Discord unfurls a bare URL, so VIDEO_URL keeps its existing behaviour."""
    ch, target = _channel(monkeypatch)
    asyncio.run(ch._async_send(Reply(ReplyType.VIDEO_URL, "https://example.com/clip.mp4"), 7))

    args, kwargs = target.sends[0]
    assert args == ("https://example.com/clip.mp4",)
    assert "file" not in kwargs
