# encoding:utf-8
"""ChatChannel._decorate_reply when an ON_DECORATE_REPLY plugin drops the reply.

A plugin drops a reply by setting it to None and breaking the chain (Banwords
does this with ``reply_action: ignore``). The desire_rtype check at the end of
_decorate_reply then read ``reply.type`` on None, so every dropped reply in a
voice-reply chat (``always_reply_voice`` / ``voice_reply_voice``) ended in an
AttributeError instead of being dropped quietly.
"""
import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel import chat_channel as mod
from plugins.event import EventAction


class _DroppingPlugins:
    def emit_event(self, e_context):
        e_context["reply"] = None
        e_context.action = EventAction.BREAK_PASS
        return e_context


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setattr(mod, "PluginManager", _DroppingPlugins)
    # Skip __init__: it starts the consumer thread, which this test does not need.
    return mod.ChatChannel.__new__(mod.ChatChannel)


def test_dropped_reply_in_a_voice_reply_chat(channel):
    context = Context(ContextType.TEXT, "hi", kwargs={"desire_rtype": ReplyType.VOICE})

    assert channel._decorate_reply(context, Reply(ReplyType.TEXT, "banned")) is None


def test_dropped_reply_in_a_text_chat(channel):
    context = Context(ContextType.TEXT, "hi")

    assert channel._decorate_reply(context, Reply(ReplyType.TEXT, "banned")) is None
