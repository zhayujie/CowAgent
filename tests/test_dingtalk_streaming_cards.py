"""DingTalk streaming AI cards and markdown subset.

Covers item 2 of https://github.com/zhayujie/CowAgent/issues/3156.
dingtalk_stream is stubbed so the suite does not need the optional SDK.
"""
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock


if "dingtalk_stream" not in sys.modules:
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
        PROCESSING = 1
        INPUTING = 2
        FINISHED = 3
        FAILED = 5

    _card.CardReplier = _CardReplier
    _card.AICardReplier = _AICardReplier
    _card.AICardStatus = _AICardStatus
    sys.modules["dingtalk_stream.card_replier"] = _card


from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.dingtalk.dingtalk_stream_card import (
    DingTalkCardStreamer,
    build_dingtalk_card_finish_payload,
    sanitize_dingtalk_markdown,
)


class FakeCard:
    def __init__(self, card_id="card-1"):
        self.card_instance_id = card_id
        self.calls = []

    def ai_streaming(self, markdown, append=False):
        self.calls.append(("stream", markdown, append))

    def ai_finish(self, markdown=None, button_list=None, tips=""):
        self.calls.append(("finish", markdown, list(button_list or []), tips))

    def ai_fail(self):
        self.calls.append(("fail",))


def _context(**kwargs):
    incoming = SimpleNamespace(sender_staff_id=kwargs.get("sender_staff_id", "staff-1"))
    msg = SimpleNamespace(
        is_group=kwargs.get("isgroup", False),
        incoming_message=incoming,
        robot_code="robot-1",
        sender_staff_id=incoming.sender_staff_id,
    )
    data = {
        "receiver": kwargs.get("receiver", "staff-1"),
        "isgroup": kwargs.get("isgroup", False),
        "msg": msg,
    }
    data.update(kwargs.get("extra") or {})
    return Context(ContextType.TEXT, kwargs.get("content", "hi"), data)


def _streamer(card=None, context=None, start=None, **kwargs):
    created = []

    def start_card():
        if start is not None:
            return start()
        item = card or FakeCard()
        created.append(item)
        return item

    ctx = context if context is not None else _context()
    streamer = DingTalkCardStreamer(
        start_card=start_card,
        context=ctx,
        immediate=True,
        throttle_s=0,
        **kwargs,
    )
    streamer.created = created
    return streamer


def test_sanitize_keeps_code_lists_and_tables():
    text = """# Title

- one
- two

```python
<html>keep</html>
```

| a | b |
| --- | --- |
| 1 | 2 |
"""
    out = sanitize_dingtalk_markdown(text)
    assert "```python" in out
    assert "<html>keep</html>" in out
    assert "- one" in out
    assert "| a | b |" in out


def test_sanitize_strips_html_and_task_boxes():
    text = 'Hello<br/>world <b>bold</b> <img src="https://x/y.png">\n- [x] done\n<!--n-->'
    out = sanitize_dingtalk_markdown(text)
    assert "<br" not in out
    assert "<b>" not in out
    assert "![](https://x/y.png)" in out
    assert "- done" in out
    assert "<!--" not in out
    assert "Hello" in out
    assert "world" in out


def test_sanitize_empty_and_none():
    assert sanitize_dingtalk_markdown("") == ""
    assert sanitize_dingtalk_markdown(None) == ""


def test_stream_uses_full_snapshots_and_finishes():
    card = FakeCard()
    ctx = _context()
    streamer = _streamer(card=card, context=ctx)
    streamer.handle_event({"type": "message_update", "data": {"delta": "Hel"}})
    streamer.handle_event({"type": "message_update", "data": {"delta": "lo **world**"}})
    streamer.handle_event(
        {"type": "agent_end", "data": {"final_response": "Hello **world**"}}
    )

    streams = [item for item in card.calls if item[0] == "stream"]
    assert streams
    assert all(item[2] is False for item in streams)
    assert streams[-1][1] == "Hello **world**"
    assert card.calls[-1][0] == "finish"
    assert card.calls[-1][1] == "Hello **world**"
    assert ctx.get("dingtalk_streamed") is True


def test_tool_turn_separator_then_final_response():
    card = FakeCard()
    streamer = _streamer(card=card)
    streamer.handle_event({"type": "message_update", "data": {"delta": "looking"}})
    streamer.handle_event(
        {"type": "message_end", "data": {"tool_calls": [{"name": "read"}]}}
    )
    streamer.handle_event({"type": "message_update", "data": {"delta": "done"}})
    streamer.handle_event(
        {"type": "agent_end", "data": {"final_response": "final answer"}}
    )
    streams = [item[1] for item in card.calls if item[0] == "stream"]
    assert any("---" in text and "looking" in text for text in streams)
    assert card.calls[-1] == ("finish", "final answer", [], "")


def test_start_failure_does_not_mark_streamed():
    ctx = _context()

    def boom():
        raise RuntimeError("no permission")

    streamer = _streamer(context=ctx, start=boom)
    streamer.handle_event({"type": "message_update", "data": {"delta": "x"}})
    streamer.handle_event({"type": "agent_end", "data": {"final_response": "x"}})
    assert streamer.disabled is True
    assert ctx.get("dingtalk_streamed") is None


def test_empty_card_id_falls_back():
    ctx = _context()

    class Empty:
        card_instance_id = ""

    streamer = _streamer(context=ctx, start=lambda: Empty())
    streamer.handle_event({"type": "message_update", "data": {"delta": "x"}})
    assert streamer.disabled is True
    assert ctx.get("dingtalk_streamed") is None


def test_cancel_with_partial_finishes_and_ignores_stale_final():
    card = FakeCard()
    ctx = _context()
    streamer = _streamer(card=card, context=ctx)
    streamer.handle_event({"type": "message_update", "data": {"delta": "partial"}})
    streamer.handle_event({"type": "agent_cancelled", "data": {}})
    streamer.handle_event(
        {"type": "agent_end", "data": {"final_response": "stale", "cancelled": True}}
    )
    assert card.calls[-1][0] == "finish"
    assert card.calls[-1][1] == "partial"
    assert ctx.get("dingtalk_streamed") is True


def test_cancel_without_text_fails_card():
    card = FakeCard()
    ctx = _context()
    streamer = _streamer(card=card, context=ctx)
    streamer.card = card
    streamer.handle_event({"type": "agent_cancelled", "data": {}})
    streamer.handle_event({"type": "agent_end", "data": {"cancelled": True}})
    assert ("fail",) in card.calls
    assert ctx.get("dingtalk_streamed") is True


def test_finish_payload_adds_image_button():
    ctx = _context(extra={"image_url": "https://x/a.png", "promptEn": "a cat"})
    body, buttons = build_dingtalk_card_finish_payload(ctx, "caption")
    assert "a cat" in body
    assert "![](https://x/a.png)" in body
    assert buttons[0]["url"] == "https://x/a.png"


def test_threaded_worker_finishes_card():
    card = FakeCard()
    ctx = _context()
    streamer = DingTalkCardStreamer(
        start_card=lambda: card,
        context=ctx,
        immediate=False,
        throttle_s=0,
    )
    streamer.handle_event({"type": "message_update", "data": {"delta": "abc"}})
    streamer.handle_event({"type": "agent_end", "data": {"final_response": "abc"}})
    kinds = [item[0] for item in card.calls]
    assert "stream" in kinds
    assert kinds[-1] == "finish"
    assert ctx.get("dingtalk_streamed") is True


def _bare_channel():
    from channel.dingtalk.dingtalk_channel import DingTalkChanel

    cls = DingTalkChanel.__wrapped__
    ch = cls.__new__(cls)
    ch._robot_code = "robot-1"
    ch.logger = MagicMock()
    return ch


def test_card_disabled_does_not_attach_on_event(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": False})
    ch = _bare_channel()
    ctx = _context()
    ch._maybe_attach_dingtalk_stream(ctx)
    assert "on_event" not in ctx.kwargs


def test_card_enabled_attaches_on_event(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": True})
    ch = _bare_channel()
    ctx = _context()
    ch._maybe_attach_dingtalk_stream(ctx)
    assert callable(ctx["on_event"])


def test_group_stream_opens_card_for_whole_chat(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": True})
    ch = _bare_channel()
    seen = {}

    def fake_start(incoming, title="", logo="", recipients=None):
        seen["recipients"] = recipients
        seen["title"] = title
        return FakeCard()

    ch.ai_markdown_card_start = fake_start
    ctx = _context(isgroup=True)
    cb = ch._make_dingtalk_stream_callback(ctx)
    cb({"type": "message_update", "data": {"delta": "Hi"}})
    cb({"type": "agent_end", "data": {"final_response": "Hi"}})
    assert seen["recipients"] is None
    assert ctx.get("dingtalk_streamed") is True


def test_single_stream_targets_sender(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": True})
    ch = _bare_channel()
    seen = {}

    def fake_start(incoming, title="", logo="", recipients=None):
        seen["recipients"] = recipients
        return FakeCard()

    ch.ai_markdown_card_start = fake_start
    ctx = _context(isgroup=False)
    cb = ch._make_dingtalk_stream_callback(ctx)
    cb({"type": "agent_end", "data": {"final_response": "Hi"}})
    assert seen["recipients"] == ["staff-1"]
    assert ctx.get("dingtalk_streamed") is True


def test_send_skips_when_streamed_including_group_notice(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": True})
    ch = _bare_channel()
    texts = []
    cards = []
    ch.reply_text = lambda content, incoming: texts.append(content)
    ch.reply_ai_markdown_button = lambda *a, **k: cards.append(a)
    ctx = _context(isgroup=True)
    ctx["dingtalk_streamed"] = True
    ch.send(Reply(ReplyType.TEXT, "hello"), ctx)
    assert texts == []
    assert cards == []


def test_send_one_shot_card_still_notifies_group_when_not_streamed(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": True})
    ch = _bare_channel()
    texts = []
    cards = []
    ch.reply_text = lambda content, incoming: texts.append(content)
    ch.reply_ai_markdown_button = lambda *a, **k: cards.append(a)
    ctx = _context(isgroup=True)
    ch.send(Reply(ReplyType.TEXT, "hello"), ctx)
    assert cards
    assert any("新的消息" in str(item) for item in texts)


def test_send_plain_text_when_cards_disabled(monkeypatch):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"dingtalk_card_enabled": False})
    ch = _bare_channel()
    texts = []
    ch.reply_text = lambda content, incoming: texts.append(content)
    ch.reply_ai_markdown_button = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("card path must not run")
    )
    ctx = _context()
    ch.send(Reply(ReplyType.TEXT, "plain"), ctx)
    assert texts == ["plain"]

def test_cancel_without_card_or_text_does_not_create():
    ctx = _context()
    created = []

    def start():
        card = FakeCard()
        created.append(card)
        return card

    streamer = _streamer(context=ctx, start=start)
    streamer.handle_event({"type": "agent_cancelled", "data": {}})
    streamer.handle_event({"type": "agent_end", "data": {"cancelled": True}})
    assert created == []
    assert ctx.get("dingtalk_streamed") is None
