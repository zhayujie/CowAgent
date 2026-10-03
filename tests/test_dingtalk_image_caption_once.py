"""An image caption must reach DingTalk once, not twice.

``ChatChannel._send_reply`` sends ``reply.text_content`` as a text bubble and
then hands the *same* reply object to ``send()``. DingTalk's image branch also
sent the caption on its way to the picture, so the user read every caption
twice. Channels that do not repeat it (feishu, qq, wecom_bot) show that the
base-class send is the one that counts.

Callers that invoke ``channel.send()`` directly -- the scheduler forwards a
FILE / IMAGE_URL reply untouched, see ``integration.py:1122`` -- never go
through ``_send_reply``, so they still rely on the channel sending the caption.
Both directions are pinned below.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.dingtalk import dingtalk_channel as dc


def _dingtalk():
    """A DingTalk instance with only its outbound I/O stubbed out.

    ``reply_text`` records what the user would see, so the stubs stop at the
    point where a real send would need a token -- otherwise the failure notice
    ("\u62b1\u6b49\uff0c\u56fe\u7247\u53d1\u9001\u5931\u8d25") lands in the recording too and
    every assertion has to tell it apart from a caption.
    """
    channel = dc.DingTalkChanel.__wrapped__.__new__(dc.DingTalkChanel.__wrapped__)
    sent = []
    channel._robot_code = "rc"
    channel.reply_text = lambda text, msg=None, *a, **kw: sent.append(text)
    channel.upload_media = lambda *a, **kw: "MEDIA_ID"
    channel.get_access_token = lambda *a, **kw: None
    channel.send_image_with_media_id = lambda *a, **kw: True
    return channel, sent


def _captions(sent):
    """Just the caption texts, without DingTalk's own failure notices."""
    return [t for t in sent if "\u62b1\u6b49" not in t]


def _context():
    context = Context()
    context["channel_type"] = "dingtalk"
    context["receiver"] = "user-1"
    context["session_id"] = "s1"
    context["agent_id"] = "primary"
    context["msg"] = types.SimpleNamespace(
        robot_code="rc", is_group=False, incoming_message=None
    )
    return context


class DingTalkImageCaptionTest(unittest.TestCase):

    def test_a_caption_reaches_dingtalk_once_through_send_reply(self):
        channel, sent = _dingtalk()
        reply = Reply(ReplyType.IMAGE_URL, "https://cdn/x.png")
        reply.text_content = "这是你要的图"

        ChatChannel._send_reply(channel, _context(), reply)

        self.assertEqual(
            _captions(sent), ["这是你要的图"],
            f"the caption should arrive once, got {sent}",
        )

    def test_an_image_without_a_caption_is_unaffected(self):
        channel, sent = _dingtalk()

        ChatChannel._send_reply(
            channel, _context(), Reply(ReplyType.IMAGE_URL, "https://cdn/y.png")
        )

        self.assertEqual(_captions(sent), [])

    def test_a_direct_send_still_delivers_the_caption(self):
        # The scheduler hands the reply to send() without going through
        # _send_reply, so the channel is the only thing that can send it.
        channel, sent = _dingtalk()
        reply = Reply(ReplyType.IMAGE_URL, "https://cdn/z.png")
        reply.text_content = "定时任务的答案"

        channel.send(reply, _context())

        self.assertEqual(_captions(sent), ["定时任务的答案"])

    def test_the_caption_flag_does_not_outlive_the_context(self):
        # A fresh Context is built per inbound message (chat_channel.py:46), so
        # the flag cannot leak into a later turn -- which would silently swallow
        # the next image's caption. Two turns, two captions.
        channel, sent = _dingtalk()

        for caption in ("第一轮", "第二轮"):
            reply = Reply(ReplyType.IMAGE_URL, "https://cdn/x.png")
            reply.text_content = caption
            ChatChannel._send_reply(channel, _context(), reply)

        self.assertEqual(_captions(sent), ["第一轮", "第二轮"])

    def test_two_images_in_one_turn_each_keep_their_caption(self):
        # One agent turn can produce several files. The flag is set on the
        # context, so a second image in the same turn must not be silenced.
        channel, sent = _dingtalk()
        context = _context()

        for caption in ("第一张", "第二张"):
            reply = Reply(ReplyType.IMAGE_URL, "https://cdn/x.png")
            reply.text_content = caption
            ChatChannel._send_reply(channel, context, reply)

        self.assertEqual(_captions(sent), ["第一张", "第二张"])


if __name__ == "__main__":
    unittest.main()