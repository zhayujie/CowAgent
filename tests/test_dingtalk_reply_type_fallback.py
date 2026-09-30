# encoding:utf-8
"""DingTalk outbound ERROR/INFO replies.

``ChatChannel._decorate_reply`` keeps ``ERROR``/``INFO`` as they are (it only
prefixes the text) and ``_send_reply`` hands them to ``send()`` through its last
``else`` branch. ``DingTalkChanel.send()`` covered IMAGE_URL, FILE, VOICE and
TEXT only, so each of those replies came back from ``send()`` without a single
API call: an agent failure never reached the chat, and neither did a godcmd or
plugin message. The QQ channel answers the same situation with a text fallback.

The optional ``dingtalk_stream`` SDK is stubbed by the streaming-card suite, so
that stub is reused here instead of copied a third time.
"""
from bridge.reply import Reply, ReplyType
from tests.test_dingtalk_streaming_cards import _bare_channel, _context


def _channel(rejected=False):
    """A channel whose webhook transport is recorded instead of called.

    ``reply_markdown`` returning a non-zero ``errcode`` is how DingTalk rejects
    a markdown message while still answering HTTP 200, which is what the
    existing text path already falls back on.
    """
    ch = _bare_channel()
    markdowns = []
    texts = []

    def reply_markdown(title, content, incoming):
        markdowns.append((title, content))
        return {"errcode": 400, "errmsg": "bad"} if rejected else {"errcode": 0}

    ch.reply_markdown = reply_markdown
    ch.reply_text = lambda content, incoming: texts.append(content)
    return ch, markdowns, texts


def test_agent_error_reaches_the_chat_as_text(monkeypatch):
    """The bridge reports a failed turn as Reply(ERROR, ...) for every channel."""
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": False})
    ch, markdowns, texts = _channel()
    ch.send(Reply(ReplyType.ERROR, "Agent error: connection reset"), _context())

    assert [content for _, content in markdowns] == ["Agent error: connection reset"]
    assert texts == []


def test_plugin_info_message_reaches_the_chat_as_text(monkeypatch):
    """godcmd and the plugins answer commands with Reply(INFO, markdown text)."""
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": False})
    ch, markdowns, _ = _channel()
    ch.send(Reply(ReplyType.INFO, "**记忆已清除**"), _context())

    assert [content for _, content in markdowns] == ["**记忆已清除**"]


def test_error_reaches_a_group_chat(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": True})
    ch, markdowns, texts = _channel()
    ch.send(Reply(ReplyType.ERROR, "Agent error: quota exceeded"), _context(isgroup=True))

    assert [content for _, content in markdowns] == ["Agent error: quota exceeded"]
    # The card API cannot render a reply that is not the streamed text, so the
    # session webhook is used with no card call at all.
    assert texts == []


def test_rejected_markdown_still_delivers_the_error(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": False})
    ch, markdowns, texts = _channel(rejected=True)
    ch.send(Reply(ReplyType.ERROR, "Agent error: timeout"), _context())

    assert markdowns, "the markdown attempt should be made first"
    assert texts == ["Agent error: timeout"]


def test_error_without_content_sends_nothing(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": False})
    ch, markdowns, texts = _channel()
    ch.send(Reply(ReplyType.ERROR, None), _context())

    assert markdowns == []
    assert texts == []


def test_unsendable_media_type_is_reported_instead_of_vanishing(monkeypatch):
    """VIDEO_URL is extracted out of a text reply by ChatChannel.

    That reply cannot go through this channel, but a silent return leaves no
    trace of why the video the user asked for never arrived.
    """
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": False})
    ch, markdowns, texts = _channel()
    warnings = []
    ch.logger.warning = lambda *a, **k: warnings.append(" ".join(str(item) for item in a))
    monkeypatch.setattr(mod, "logger", ch.logger)

    ch.send(Reply(ReplyType.VIDEO_URL, "https://example.com/clip.mp4"), _context())

    assert markdowns == []
    assert texts == []
    assert any("VIDEO_URL" in message for message in warnings)
