# encoding:utf-8
"""ChatChannel._decorate_reply on a reply type the channel cannot send.

The reply is turned into an ERROR that names the type the channel refused.
The type was overwritten with ERROR before it was put into the message, so the
user read "Unsupported message type: ERROR" and the real type (VOICE, IMAGE,
...) never appeared anywhere in the chat.
"""
import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel import chat_channel as mod


class _PassThroughPlugins:
    def emit_event(self, e_context):
        return e_context


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setattr(mod, "PluginManager", _PassThroughPlugins)
    # Skip __init__: it starts the consumer thread, which this test does not need.
    ch = mod.ChatChannel.__new__(mod.ChatChannel)
    ch.NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE, ReplyType.IMAGE]
    return ch


@pytest.mark.parametrize("rtype", [ReplyType.VOICE, ReplyType.IMAGE])
def test_error_names_the_refused_type(channel, rtype):
    reply = channel._decorate_reply(Context(ContextType.TEXT, "hi"), Reply(rtype, "/tmp/x"))

    assert reply.type == ReplyType.ERROR
    assert reply.content.endswith(": " + str(rtype))
    assert not reply.content.endswith(": ERROR")
