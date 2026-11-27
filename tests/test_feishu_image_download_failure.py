# encoding:utf-8
"""A single image that failed to download must not be dropped in silence.

The image is cached for the user's next question, so a failed download leaves
nothing behind: the user sends a picture, sees no reaction, then asks about it and
the agent answers that it cannot see any image. The file branch of the same
handler already tells the user, with the comment "避免静默丢失".
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.feishu import feishu_message
from channel.feishu.feishu_channel import FeiShuChanel
from common.expired_dict import ExpiredDict


def _image_event(image_key="img_1"):
    return {
        "app_id": "cli_bot",
        "sender": {"sender_id": {"open_id": "ou_user"}},
        "message": {
            "message_id": "om_img",
            "chat_id": "oc_chat",
            "chat_type": "p2p",
            "message_type": "image",
            "create_time": str(int(time.time() * 1000)),
            "content": json.dumps({"image_key": image_key}),
        },
    }


def _channel(monkeypatch, downloaded):
    channel = FeiShuChanel()
    channel.receivedMsgs = ExpiredDict(60)
    monkeypatch.setattr(channel, "fetch_access_token", lambda: "tenant-token")
    monkeypatch.setattr(feishu_message.FeishuMessage, "_download_image",
                        lambda self, message_id, image_key: downloaded)
    sent = []
    monkeypatch.setattr(channel, "_send", lambda reply, context: sent.append(reply))
    return channel, sent


def test_an_image_that_could_not_be_downloaded_is_reported(monkeypatch):
    channel, sent = _channel(monkeypatch, downloaded=None)

    channel._handle_message_event(_image_event())

    assert len(sent) == 1, "the user got no reaction at all to a picture that was lost"
    assert "图片下载失败" in sent[0].content


def test_a_downloaded_image_is_cached_without_a_notice(monkeypatch, tmp_path):
    path = tmp_path / "pic.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    channel, sent = _channel(monkeypatch, downloaded=str(path))

    channel._handle_message_event(_image_event())

    assert sent == [], "a successful download must stay silent"


def test_a_failed_file_still_gets_the_file_wording(monkeypatch):
    """The control: generalising the notice must not change the file wording."""
    channel, sent = _channel(monkeypatch, downloaded=None)

    def boom(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(feishu_message.FeishuMessage, "prepare", boom)
    event = _image_event()
    event["message"]["message_type"] = "file"
    event["message"]["content"] = json.dumps({"file_key": "fk_1", "file_name": "a.txt"})

    channel._handle_message_event(event)

    assert len(sent) == 1
    assert sent[0].content == "⚠️ 文件下载失败，请重新发送：boom"
