# encoding:utf-8
"""Telegram's length limits count UTF-16 code units, not characters.

The caption gate used len() and the text path split at 4000 *characters*,
so astral-dense text (emoji weigh 2 units each) passed every local check and
was rejected by the API — and both BadRequest fallbacks resent the *same*
payload, which failed identically, dropping the whole file message or reply.
These tests pin the UTF-16 accounting and the degraded-path re-split.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import Reply, ReplyType
from channel.telegram.telegram_channel import TelegramChannel

# @singleton wraps the class; the bare class rides on __wrapped__.
_TelegramChannel = TelegramChannel.__wrapped__
from channel.telegram.telegram_markdown import (
    TEXT_LIMIT,
    split_plain_by_utf16,
    utf16_len,
)

EMOJI = "\U0001f600"  # one character, two UTF-16 units


class TestUtf16Helpers(unittest.TestCase):

    def test_utf16_len_counts_astral_characters_double(self):
        self.assertEqual(utf16_len("abc"), 3)
        self.assertEqual(utf16_len(EMOJI), 2)
        self.assertEqual(utf16_len("a" + EMOJI + "b"), 4)

    def test_plain_split_respects_the_unit_budget(self):
        text = EMOJI * 5000  # 10000 UTF-16 units
        parts = split_plain_by_utf16(text, 4000)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(utf16_len(part), 4000)
        self.assertEqual("".join(parts), text)

    def test_short_text_is_returned_whole(self):
        self.assertEqual(split_plain_by_utf16("hello", 4000), ["hello"])


class _FakeBot:
    def __init__(self, reject_html_captions=False):
        self.messages = []
        self.files = []
        self.reject_html_captions = reject_html_captions

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)

    async def send_video(self, **kwargs):
        if self.reject_html_captions and kwargs.get("caption"):
            from telegram.error import BadRequest

            raise BadRequest("caption is too long")
        self.files.append(kwargs)


class _Shell:
    """Just enough channel for the send paths under test."""

    def __init__(self, bot):
        self._bot = bot

    async def _send_with_retry(self, send, label=None):
        return await send()

    _send_text = _TelegramChannel._send_text
    _async_send = _TelegramChannel._async_send


class TestSendTextBudget(unittest.TestCase):

    def test_an_astral_dense_reply_is_sent_within_the_cap(self):
        bot = _FakeBot()
        shell = _Shell(bot)
        text = EMOJI * 4500  # 9000 units in one 4500-char "chunk"

        asyncio.run(shell._send_text(text, 1, None))

        self.assertGreater(len(bot.messages), 1)
        for msg in bot.messages:
            self.assertLessEqual(utf16_len(msg["text"]), TEXT_LIMIT,
                                 "a message over the UTF-16 cap was sent")
        self.assertEqual("".join(m["text"] for m in bot.messages), text)


class TestCaptionFallback(unittest.TestCase):

    def test_a_rejected_caption_is_delivered_as_text_not_resent(self):
        bot = _FakeBot(reject_html_captions=True)
        shell = _Shell(bot)
        reply = Reply(ReplyType.VIDEO, os.devnull)  # any openable path
        reply.file_name = "clip.mp4"
        # _async_send reads the caption from text_content. Short enough to
        # pass every local check; the fake bot rejects it on the API side.
        reply.text_content = "watch this " + EMOJI

        with patch.object(_TelegramChannel, "_is_video_local", lambda path: True, create=True):
            asyncio.run(shell._async_send(reply, 1, None))

        # The file went out bare (no caption on it).
        self.assertEqual(len(bot.files), 1)
        self.assertFalse(bot.files[0].get("caption"))
        # The caption itself arrived as a follow-up text message.
        captions = [m["text"] for m in bot.messages]
        self.assertTrue(captions, "the rejected caption was dropped instead of re-sent as text")


if __name__ == "__main__":
    unittest.main()
