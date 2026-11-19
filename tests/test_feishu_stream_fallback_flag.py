# encoding:utf-8
"""Feishu streaming must clear the streamed flag when nothing was delivered.

Both stream callbacks set context["feishu_streamed"] = True as soon as
agent_end arrives, so chat_channel skips its plain send(). But the agent_end
handler can still return without delivering anything:

- the bot lacks cardkit:card:write (or the network fails), the card is
  created only at agent_end (very fast replies never send a message_update),
  and _create_and_send_card marks the run disabled — the docstring promises
  "创建卡片实体失败 → 不设置 feishu_streamed 标记，让 chat_channel 走普通文本
  回复路径", but the flag was already set, so the user got NOTHING.

These tests pin the flag being undone when card creation fails, kept on
success and on a cancelled tool turn, with requests mocked at the module
boundary.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.feishu.feishu_channel import FeiShuChanel


def _channel():
    cls = FeiShuChanel.__wrapped__ if hasattr(FeiShuChanel, "__wrapped__") else FeiShuChanel
    ch = cls.__new__(cls)
    ch.feishu_domain = "https://open.feishu.cn"
    return ch


def _context():
    return {"receiver": "ou_1", "isgroup": False, "receive_id_type": "open_id"}


def _ok_card_response():
    res = MagicMock()
    res.json.return_value = {"code": 0, "data": {"card_id": "card_1", "message_id": "msg_1"}}
    return res


def _denied_card_response():
    res = MagicMock()
    res.json.return_value = {"code": 99991672, "msg": "no cardkit permission"}
    return res


class TestStreamedFlagFallback(unittest.TestCase):

    def _callback(self, context):
        return self._channel_obj._make_feishu_stream_callback_plain(context, "token")

    def setUp(self):
        self._channel_obj = _channel()

    def test_card_creation_failure_at_agent_end_undoes_the_flag(self):
        context = _context()
        on_event = self._callback(context)

        with patch("channel.feishu.feishu_channel.requests.post",
                   return_value=_denied_card_response()), \
                patch("channel.feishu.feishu_channel.logger"):
            on_event({"type": "agent_end", "data": {"final_response": "hello"}})

        self.assertFalse(context.get("feishu_streamed"),
                         "the text fallback must stay enabled when no card was delivered")

    def test_cancelled_without_a_card_keeps_the_flag(self):
        # A tool turn's card was already finalized (and delivered) in
        # message_end, so has_card is False here while the
        # intermediate text HAS been shown. Clearing the flag would make
        # send() deliver final_response — that same text — a second time.
        context = _context()
        on_event = self._callback(context)

        with patch("channel.feishu.feishu_channel.logger"):
            on_event({"type": "agent_cancelled", "data": {}})
            on_event({"type": "agent_end", "data": {"final_response": "partial"}})

        self.assertTrue(context.get("feishu_streamed"))

    def test_successful_delivery_keeps_the_flag(self):
        context = _context()
        on_event = self._callback(context)

        with patch("channel.feishu.feishu_channel.requests.post",
                   return_value=_ok_card_response()), \
                patch("channel.feishu.feishu_channel.requests.put") as put, \
                patch("channel.feishu.feishu_channel.requests.patch"), \
                patch("channel.feishu.feishu_channel.resolve_markdown_images",
                      side_effect=lambda text, fn: text), \
                patch("channel.feishu.feishu_channel.logger"):
            on_event({"type": "message_update", "data": {"delta": "hel"}})
            on_event({"type": "agent_end", "data": {"final_response": "hello"}})

        self.assertTrue(context.get("feishu_streamed"))
        self.assertTrue(put.called)


if __name__ == "__main__":
    unittest.main()
