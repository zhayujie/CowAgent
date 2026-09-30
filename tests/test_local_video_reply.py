# encoding:utf-8
"""Slack, Telegram, Feishu, DingTalk and wechatmp upload a local ``ReplyType.VIDEO`` instead of posting its path.

``ChatChannel`` hands an agent-produced video over as
``Reply(ReplyType.VIDEO, "file://" + path)``; without a VIDEO branch the reply
fell through to the plain-text fallback and the user got the raw path.
"""
import asyncio
import json
import sys
import types

import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType


def test_slack_uploads_a_local_video():
    from channel.slack import slack_channel as mod

    uploads, posts = [], []
    ch = mod.SlackChannel.__wrapped__.__new__(mod.SlackChannel.__wrapped__)
    ch._client = types.SimpleNamespace(
        files_upload_v2=lambda **kw: uploads.append(kw),
        chat_postMessage=lambda **kw: posts.append(kw),
    )

    ch._do_send(Reply(ReplyType.VIDEO, "file:///srv/cow/tmp/clip.mp4"), "C1", "1.0")

    assert posts == []
    assert uploads[0]["file"] == "/srv/cow/tmp/clip.mp4"


def test_telegram_sends_a_local_video_as_video(monkeypatch, tmp_path):
    from channel.telegram import telegram_channel as mod

    telegram = types.ModuleType("telegram")
    constants = types.ModuleType("telegram.constants")
    constants.ParseMode = types.SimpleNamespace(HTML="HTML")
    error = types.ModuleType("telegram.error")
    for name in ("BadRequest", "NetworkError", "TimedOut"):
        setattr(error, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "telegram", telegram)
    monkeypatch.setitem(sys.modules, "telegram.constants", constants)
    monkeypatch.setitem(sys.modules, "telegram.error", error)

    calls = []

    class Bot:
        async def send_video(self, **kw):
            calls.append(("video", kw["video"].name))

        async def send_document(self, **kw):
            calls.append(("document", kw["document"].name))

        async def send_message(self, **kw):
            calls.append(("message", kw["text"]))

    clip = tmp_path / "clip"
    clip.write_bytes(b"video")
    ch = mod.TelegramChannel.__wrapped__.__new__(mod.TelegramChannel.__wrapped__)
    ch._bot = Bot()

    asyncio.run(ch._async_send(Reply(ReplyType.VIDEO, f"file://{clip}"), 7, None))

    assert calls == [("video", str(clip))]


# Feishu and DingTalk had the same gap, and both already own the upload helper:
# FeiShuChanel._upload_video_url (used by its FILE branch for .mp4) and
# DingTalkChanel.upload_media(media_type="video"). Neither send() dispatched
# ReplyType.VIDEO, so Feishu posted the raw "file://" path as text and DingTalk
# logged "Unsupported reply type" and sent nothing.


def _feishu_channel(monkeypatch, posts):
    from channel.feishu import feishu_channel as mod

    def post(url=None, headers=None, params=None, json=None, timeout=None):
        posts.append({"url": url, "params": params, "json": json})
        return types.SimpleNamespace(json=lambda: {"code": 0, "data": {}})

    ch = mod.FeiShuChanel.__wrapped__.__new__(mod.FeiShuChanel.__wrapped__)
    ch.fetch_access_token = lambda: "token"
    monkeypatch.setattr(mod.requests, "post", post)
    return ch


def _feishu_context():
    return Context(ContextType.TEXT, "", {"receiver": "ou-1", "isgroup": False})


def test_feishu_uploads_a_local_video_as_media(monkeypatch):
    posts = []
    uploads = []
    ch = _feishu_channel(monkeypatch, posts)

    def upload(video_url, access_token):
        uploads.append((video_url, access_token))
        return {"file_key": "fk-1", "duration": 4200}

    ch._upload_video_url = upload

    # No known video suffix: the reply type is what says this is a video.
    ch.send(Reply(ReplyType.VIDEO, "file:///srv/cow/tmp/clip"), _feishu_context())

    assert uploads == [("file:///srv/cow/tmp/clip", "token")]
    assert len(posts) == 1, posts
    body = posts[0]["json"]
    assert body["msg_type"] == "media", body
    assert json.loads(body["content"]) == {"file_key": "fk-1", "duration": 4200}


def test_feishu_still_sends_a_plain_file(monkeypatch):
    posts = []
    uploads = []
    ch = _feishu_channel(monkeypatch, posts)
    ch._upload_video_url = lambda *a: uploads.append(a)
    ch._upload_file_url = lambda url, token: "fk-2"

    ch.send(Reply(ReplyType.FILE, "file:///srv/cow/notes.txt"), _feishu_context())

    assert uploads == []
    assert len(posts) == 1, posts
    assert posts[0]["json"]["msg_type"] == "file"


def _dingtalk_channel():
    from channel.dingtalk import dingtalk_channel as mod

    ch = mod.DingTalkChanel.__wrapped__.__new__(mod.DingTalkChanel.__wrapped__)
    ch._robot_code = "rb-1"
    ch.get_access_token = lambda: "token"
    ch.reply_text = lambda *a, **k: None
    uploads, sent = [], []

    def upload_media(path, media_type="image"):
        uploads.append((path, media_type))
        return "media-1"

    def send_file_message(access_token, incoming_message, msg_key, msg_param, is_group):
        sent.append((msg_key, msg_param))
        return True

    ch.upload_media = upload_media
    ch._send_file_message = send_file_message
    context = Context(
        ContextType.TEXT,
        "",
        {
            "receiver": "u-1",
            "msg": types.SimpleNamespace(
                is_group=False, incoming_message=object(), robot_code="rb-1"
            ),
        },
    )
    return ch, context, uploads, sent


def test_dingtalk_uploads_a_local_video_as_video():
    ch, context, uploads, sent = _dingtalk_channel()

    ch.send(Reply(ReplyType.VIDEO, "file:///srv/cow/tmp/clip.mp4"), context)

    assert uploads == [("file:///srv/cow/tmp/clip.mp4", "video")], uploads
    assert [key for key, _ in sent] == ["sampleVideo"], sent


def test_dingtalk_still_sends_a_plain_file():
    ch, context, uploads, sent = _dingtalk_channel()

    ch.send(Reply(ReplyType.FILE, "file:///srv/cow/notes.txt"), context)

    assert uploads == [("file:///srv/cow/notes.txt", "file")], uploads
    assert [key for key, _ in sent] == ["sampleFile"], sent


# wechatmp read the same reply as an open handle, so the "file://" path raised
# AttributeError before any upload was attempted. ChatChannel's send wrapper
# retried twice and swallowed it, which left the user with the text answer and
# no video. Both of its send modes share the branch.


def _wechatmp_channel(passive):
    from collections import defaultdict
    from unittest.mock import Mock

    from channel.wechatmp import wechatmp_channel as mod

    ch = mod.WechatMPChannel.__wrapped__.__new__(mod.WechatMPChannel.__wrapped__)
    ch.passive_reply = passive
    ch.cache_dict = defaultdict(list)
    ch.client = Mock()
    ch.client.material.add.return_value = {"media_id": "media-1"}
    ch.client.media.upload.return_value = {"media_id": "media-1"}
    return ch


@pytest.mark.parametrize("passive", [True, False])
def test_wechatmp_uploads_a_local_video(passive, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video-bytes")
    ch = _wechatmp_channel(passive)

    ch.send(
        Reply(ReplyType.VIDEO, f"file://{clip}"),
        {"receiver": "u1", "msg": types.SimpleNamespace(msg_id="m1")},
    )

    upload = ch.client.material.add if passive else ch.client.media.upload
    media_type, (filename, stream, content_type) = upload.call_args.args
    assert (media_type, filename, content_type) == ("video", "u1-m1.mp4", "video/mp4")
    assert stream.read() == b"video-bytes"
    if passive:
        assert ch.cache_dict["u1"] == [("video", "media-1")]
    else:
        assert ch.client.message.send_video.call_args.args == ("u1", "media-1")
