"""A WeCom group message has to reach the agent, marked as an @-mention.

WeCom only pushes a group message once the bot was addressed in it, and
WecomBotMessage strips that "@" out of the text before handing it on. The
message therefore has to record that it was addressed: ChatChannel's group gate
lets a group message through when it matches a configured prefix/keyword or when
it sets is_at, and a text whose "@bot ..." has already been stripped matches
neither -- so the message was dropped and the bot never answered in a group,
even though docs/channels/wecom-bot.mdx lists "Group chat (@bot)" as supported.

Both receive paths (websocket and webhook callback) hand the message to
ChatChannel._compose_context; None means there was nothing to reply to.
"""
import pytest

from bridge.context import ContextType
from channel.chat_channel import ChatChannel
from channel.wecom_bot.wecom_bot_message import WecomBotMessage
from config import conf

GROUP_PREFIX = ["@bot"]


def _body(msgtype="text", chattype="group", content="@Robot hello"):
    body = {
        "msgid": "msg-1",
        "create_time": 1758000000,
        "msgtype": msgtype,
        "chattype": chattype,
        "aibotid": "bot-1",
        "chatid": "chat-1",
        "from": {"userid": "user-1"},
    }
    body[msgtype] = {"content": content}
    return body


def _channel():
    """A ChatChannel without its consume() thread -- _compose_context needs no more."""
    channel = ChatChannel.__new__(ChatChannel)
    channel.name = "Robot"
    channel.user_id = "bot-1"
    channel.channel_type = "wecom_bot"
    return channel


@pytest.fixture(autouse=True)
def group_gate_config():
    """The channel constructor whitelists every group. The prefix stays at its
    documented default, so a group message can only pass the gate through is_at.
    """
    config = conf()
    keys = ("group_name_white_list", "group_chat_prefix", "group_at_off")
    saved = {key: config.get(key) for key in keys}
    config["group_name_white_list"] = ["ALL_GROUP"]
    config["group_chat_prefix"] = GROUP_PREFIX
    config["group_at_off"] = False
    yield
    for key, value in saved.items():
        config[key] = value


@pytest.mark.parametrize("msgtype", ["text", "voice"])
def test_a_group_message_reaches_the_agent(msgtype):
    msg = WecomBotMessage(_body(msgtype), is_group=True)

    context = _channel()._compose_context(
        ContextType.TEXT, msg.content, isgroup=True, msg=msg, no_need_at=True
    )

    assert context is not None, "a group message must not be dropped"
    assert msg.is_at is True, "a group message is by definition addressed to the bot"
    assert context["receiver"] == "chat-1", "the reply has to go back to the group"
    assert context.content == "hello"


def test_the_mention_is_still_stripped_from_the_text():
    msg = WecomBotMessage(_body(content="@Robot hello there"), is_group=True)

    assert msg.content == "hello there"


def test_a_direct_message_is_not_marked_as_a_mention():
    """A DM is triggered by single_chat_prefix, so is_at stays off."""
    msg = WecomBotMessage(_body(chattype="single", content="hello"), is_group=False)

    assert msg.is_at is False
    assert msg.content == "hello"
