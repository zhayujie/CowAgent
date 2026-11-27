"""An image reply's caption is sent once: as its own text, not again with the image."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from tests.sleep_stub import stub_sleep


def test_image_is_sent_without_its_caption_after_the_caption_bubble(monkeypatch):
    channel = ChatChannel.__new__(ChatChannel)
    sent = []
    channel._send = lambda reply, context, retry_cnt=0: sent.append((reply.type, reply.content, getattr(reply, "text_content", None)))
    reply = Reply(ReplyType.IMAGE_URL, "https://example.invalid/a.png")
    reply.text_content = "Here is the chart"
    context = Context()
    context["channel_type"] = "dingtalk"

    stub_sleep(monkeypatch)
    channel._send_reply(context, reply)

    assert sent == [
        (ReplyType.TEXT, "Here is the chart", None),
        (ReplyType.IMAGE_URL, "https://example.invalid/a.png", None),
    ]
    assert reply.text_content == "Here is the chart"
