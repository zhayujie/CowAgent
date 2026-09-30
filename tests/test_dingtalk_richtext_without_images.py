"""A DingTalk richText message without images still has to reach the agent.

``DingTalkMessage`` sends both ``picture`` and ``richText`` through one branch and,
when ``event.get_image_list()`` comes back empty, its fallback classifies the message
as ``ContextType.IMAGE`` with the placeholder content ``[未找到图片]``
(channel/dingtalk/dingtalk_message.py). But a richText message may carry only
formatted text -- DingTalk uses ``richText`` for styled input, and the image list is
empty whenever none of the parts is an image -- so that text is thrown away.

The channel then consumes the message without ever producing a context: both the
single-chat and group receive paths cache only ``cmsg.image_path`` for an IMAGE and
``return`` (channel/dingtalk/dingtalk_channel.py:689-694 and :767-772), and the
fallback above never sets ``image_path``. The user is left with no reply at all.
"""

import sys
import types
from types import SimpleNamespace

try:
    import dingtalk_stream  # noqa: F401  -- the declared dependency
except ImportError:
    # Same stand-in the other DingTalk tests install, so that this file neither
    # needs the optional SDK nor leaves a thinner module behind for them.
    _ds = types.ModuleType("dingtalk_stream")

    class _ChatbotMessage:
        pass

    class _AckMessage:
        STATUS_OK = 0
        STATUS_SYSTEM_EXCEPTION = 1

    class _ChatbotHandler:
        def ai_markdown_card_start(self, *args, **kwargs):
            raise AssertionError("ai_markdown_card_start must be mocked in tests")

        def reply_text(self, *args, **kwargs):
            return None

        def reply_ai_markdown_button(self, *args, **kwargs):
            return None

    _ds.ChatbotMessage = _ChatbotMessage
    _ds.AckMessage = _AckMessage
    _ds.ChatbotHandler = _ChatbotHandler
    _ds.CallbackMessage = object
    sys.modules["dingtalk_stream"] = _ds

    _card = types.ModuleType("dingtalk_stream.card_replier")

    class _CardReplier:
        def __init__(self, *args, **kwargs):
            pass

    class _AICardReplier(_CardReplier):
        pass

    class _AICardStatus:
        PROCESSING = "PROCESSING"

    _card.CardReplier = _CardReplier
    _card.AICardReplier = _AICardReplier
    _card.AICardStatus = _AICardStatus
    sys.modules["dingtalk_stream.card_replier"] = _card

from bridge.context import ContextType
from channel.dingtalk.dingtalk_message import DingTalkMessage


class FakeEvent:
    """The attributes ``DingTalkMessage`` reads off a ChatbotMessage."""

    def __init__(self, message_type="richText", conversation_type="1", **kwargs):
        self.message_id = kwargs.get("message_id", "mid-1")
        self.message_type = message_type
        self.conversation_id = kwargs.get("conversation_id", "cid-1")
        self.conversation_type = conversation_type
        self.sender_id = kwargs.get("sender_id", "sender-1")
        self.sender_staff_id = kwargs.get("sender_staff_id", "staff-1")
        self.chatbot_user_id = kwargs.get("chatbot_user_id", "bot-1")
        self.conversation_title = kwargs.get("conversation_title", "title")
        self.robot_code = kwargs.get("robot_code", "robot-1")
        self.create_at = kwargs.get("create_at", 1_700_000_000_000)
        self.image_content = kwargs.get("image_content")
        self.rich_text_content = kwargs.get("rich_text_content")
        self.text = kwargs.get("text", SimpleNamespace(content=""))
        self.extensions = kwargs.get("extensions", {})
        self._image_list = kwargs.get("image_list", [])
        self._text_list = kwargs.get("text_list", [])

    def get_image_list(self):
        return list(self._image_list)

    def get_text_list(self):
        return list(self._text_list)


class FakeHandler:
    def get_image_download_url(self, download_code):
        raise AssertionError("no image should be downloaded when there is none")


def test_rich_text_without_images_becomes_a_text_message():
    # The text is the whole payload of this message, so it has to be what the
    # agent receives -- not a placeholder the channel drops on the floor.
    msg = DingTalkMessage(
        FakeEvent(
            message_type="richText",
            rich_text_content=SimpleNamespace(rich_text_list=[]),
            text_list=["帮我", "总结一下"],
        ),
        FakeHandler(),
    )

    assert msg.ctype == ContextType.TEXT
    assert msg.content == "帮我总结一下"


def test_rich_text_with_neither_images_nor_text_keeps_the_placeholder():
    # Nothing can be recovered from such a message; the IMAGE placeholder is the
    # honest answer, and the fix must not turn it into an empty text context.
    msg = DingTalkMessage(
        FakeEvent(message_type="richText", rich_text_content=None, text_list=[]),
        FakeHandler(),
    )

    assert msg.ctype == ContextType.IMAGE
    assert msg.content == "[未找到图片]"


def test_picture_without_an_image_list_is_still_an_image():
    # ``picture`` reaches the same fallback and has no text to fall back on.
    msg = DingTalkMessage(
        FakeEvent(message_type="picture", image_list=[], text_list=["ignored"]),
        FakeHandler(),
    )

    assert msg.ctype == ContextType.IMAGE
    assert msg.content == "[未找到图片]"
