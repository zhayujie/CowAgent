# encoding:utf-8
"""
Regression tests for the Slack and Discord outbound retry path.

The retry contract lives in the caller, ``channel/chat_channel.py::_send``,
which retries ``self.send(reply, context)`` twice on any exception. Both
``SlackChannel.send`` and ``DiscordChannel.send`` swallowed every exception
internally, so a rate-limited or transiently failing API call produced zero
retries and the reply was simply lost. Discord swallowed twice: ``send``
caught what ``future.result()`` raised, and ``_async_send`` had already
discarded the coroutine's own exception, so the outer handler had nothing
left to see even when it wanted to re-raise.

These tests assert that a failing send propagates -- the same deliberate
choice the Feishu channel already made ("Raise so a scheduled push isn't
silently marked delivered") -- while a successful send still returns normally
and logs, so the fix cannot turn a delivery into an exception.

Channels are built with ``__wrapped__`` + ``__new__`` (``@singleton``), and
only the attribute ``send()`` actually touches is stubbed: ``_do_send`` for
Slack, and the loop plus ``_client.get_channel`` for Discord.
"""
import asyncio
import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import Reply, ReplyType
from channel.discord import discord_channel as discord_mod
from channel.discord.discord_channel import DiscordChannel
from channel.slack import slack_channel as slack_mod
from channel.slack.slack_channel import SlackChannel


def _slack_channel():
    """A Slack channel carrying only what ``send()`` reads.

    ``@singleton`` exposes the undecorated class as ``__wrapped__`` and
    ``__init__`` would need a real bot token, so the instance is built
    bare. ``send()`` only checks ``self._client is None`` before delegating
    to ``_do_send``, so any non-None sentinel keeps it on the real path.
    """
    cls = SlackChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._client = object()
    return ch


def _discord_channel(loop, channel_obj):
    """A Discord channel whose loop thread owns ``channel_obj``."""
    cls = DiscordChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._loop = loop
    ch._client = SimpleNamespace(get_channel=lambda channel_id: channel_obj)
    return ch


class _LoopThread:
    """A running asyncio loop on its own thread.

    ``send()`` hands the coroutine to the loop via
    ``asyncio.run_coroutine_threadsafe``, so a loop that is actually
    executing is required -- an idle loop would never resolve the future.
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()


class _RaisingChannel:
    """Stands in for a discord.py channel whose ``send`` hits a rate limit."""

    def __init__(self, exc):
        self.exc = exc

    async def send(self, *args, **kwargs):
        raise self.exc


class _RecordingChannel:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class TestSlackSendFailureReachesRetry(unittest.TestCase):
    def test_send_failure_propagates(self):
        """A failed Slack API call must reach ``_send``'s retry loop."""
        ch = _slack_channel()
        rate_limited = RuntimeError("slack rate limited")

        def boom(reply, channel_id, thread_ts):
            raise rate_limited

        ch._do_send = boom

        # Before the fix send() logged and returned None here, so the two
        # retries in chat_channel._send never happened and the reply died.
        with self.assertRaises(RuntimeError) as caught:
            ch.send(
                Reply(ReplyType.TEXT, "hi"),
                {"slack_channel": "C1", "slack_thread_ts": "1.0"},
            )
        self.assertIs(caught.exception, rate_limited)

    def test_failure_is_still_logged(self):
        """The existing log line is useful and must survive the re-raise."""
        ch = _slack_channel()

        def boom(reply, channel_id, thread_ts):
            raise RuntimeError("slack rate limited")

        ch._do_send = boom

        with patch.object(slack_mod.logger, "error") as error:
            with self.assertRaises(RuntimeError):
                ch.send(
                    Reply(ReplyType.TEXT, "hi"), {"slack_channel": "C1"}
                )

        self.assertTrue(error.called)
        self.assertIn("send failed", error.call_args.args[0])

    def test_success_returns_normally_and_logs(self):
        """The fix must not turn a successful delivery into an exception."""
        ch = _slack_channel()
        sent = []
        ch._do_send = lambda reply, channel_id, thread_ts: sent.append(
            (reply.type, channel_id, thread_ts)
        )

        with patch.object(slack_mod.logger, "info") as info:
            result = ch.send(
                Reply(ReplyType.TEXT, "hi"),
                {"slack_channel": "C1", "slack_thread_ts": "1.0"},
            )

        self.assertIsNone(result)
        self.assertEqual(sent, [(ReplyType.TEXT, "C1", "1.0")])
        self.assertTrue(info.called)

    def test_unready_client_still_drops_silently(self):
        """A missing client is not an API error and keeps its early return."""
        ch = _slack_channel()
        ch._client = None

        with patch.object(slack_mod.logger, "warning") as warning:
            self.assertIsNone(
                ch.send(Reply(ReplyType.TEXT, "hi"), {"slack_channel": "C1"})
            )

        self.assertTrue(warning.called)


class TestDiscordSendFailureReachesRetry(unittest.TestCase):
    """One loop thread is shared by the whole class.

    ``send()`` hands its coroutine to ``self._loop`` via
    ``asyncio.run_coroutine_threadsafe``, so a loop that is actually
    executing is required. Spinning up and tearing down a thread per test
    made the suite race with its own shutdown, so a single long-lived loop
    is started once and stopped once.
    """

    @classmethod
    def setUpClass(cls):
        cls.runner = _LoopThread()
        cls.loop = cls.runner.loop

    @classmethod
    def tearDownClass(cls):
        cls.runner.stop()

    def _discord_channel(self, channel_obj):
        return _discord_channel(self.loop, channel_obj)

    def _run_async_send(self, ch, reply):
        """Drive ``_async_send`` on the shared loop and wait for it."""
        return asyncio.run_coroutine_threadsafe(ch._async_send(reply, 42), self.loop)

    def test_send_failure_propagates(self):
        """A failed Discord API call must reach ``_send``'s retry loop.

        This drives the real ``_async_send``, so it only passes when both
        the coroutine and the outer handler let the error through.
        """
        rate_limited = RuntimeError("discord rate limited")
        ch = self._discord_channel(_RaisingChannel(rate_limited))

        with self.assertRaises(RuntimeError) as caught:
            ch.send(Reply(ReplyType.TEXT, "hi"), {"discord_channel_id": 42})
        self.assertIs(caught.exception, rate_limited)

    def test_async_send_propagates_to_its_caller(self):
        """The coroutine must not discard its own exception.

        ``send()`` observes the coroutine only through
        ``future.result()``. While ``_async_send`` swallowed, that call
        always returned cleanly no matter what the outer handler did.
        """
        boom = RuntimeError("discord rate limited")
        ch = self._discord_channel(_RaisingChannel(boom))

        future = self._run_async_send(ch, Reply(ReplyType.TEXT, "hi"))

        with self.assertRaises(RuntimeError) as caught:
            future.result(timeout=30)
        self.assertIs(caught.exception, boom)

    def test_async_send_failure_is_still_logged(self):
        ch = self._discord_channel(_RaisingChannel(RuntimeError("nope")))

        future = self._run_async_send(ch, Reply(ReplyType.TEXT, "hi"))

        with patch.object(discord_mod.logger, "error") as error:
            with self.assertRaises(RuntimeError):
                future.result(timeout=30)

        # Any matching call rather than the last one: the logger is shared,
        # so another thread could log after this one.
        messages = [str(call.args[0]) for call in error.call_args_list if call.args]
        self.assertTrue(
            any("_async_send error" in message for message in messages),
            f"expected an _async_send error log, got {messages!r}",
        )

    def test_success_returns_normally_and_logs(self):
        """The fix must not turn a successful delivery into an exception."""
        target = _RecordingChannel()
        ch = self._discord_channel(target)

        with patch.object(discord_mod.logger, "info") as info:
            result = ch.send(Reply(ReplyType.TEXT, "hi"), {"discord_channel_id": 42})

        self.assertIsNone(result)
        self.assertEqual(target.sent, [(("hi",), {})])
        messages = [str(call.args[0]) for call in info.call_args_list if call.args]
        self.assertTrue(
            any("sent reply" in message for message in messages),
            f"expected the sent-reply log, got {messages!r}",
        )

    def test_unready_client_still_drops_silently(self):
        ch = self._discord_channel(_RecordingChannel())
        ch._client = None

        with patch.object(discord_mod.logger, "warning") as warning:
            self.assertIsNone(
                ch.send(Reply(ReplyType.TEXT, "hi"), {"discord_channel_id": 42})
            )

        self.assertTrue(warning.called)


if __name__ == "__main__":
    unittest.main()
