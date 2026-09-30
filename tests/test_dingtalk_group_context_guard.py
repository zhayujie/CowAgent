# encoding:utf-8
"""DingTalk group messages outside the whitelist must be skipped, not crashed.

``ChatChannel._compose_context`` returns ``None`` when the group name is not in
``group_name_white_list`` (``channel/chat_channel.py``), and every channel in the
repo then guards with ``if context:``. ``handle_group`` wrote
``context['no_need_at'] = True`` one line *before* its guard, so a skipped group
message raised ``TypeError: 'NoneType' object does not support item assignment``
instead of being skipped. ``process()`` catches that and answers
``AckMessage.STATUS_SYSTEM_EXCEPTION``, while ``_check`` has already recorded the
message id in ``receivedMsgs`` — so DingTalk's redelivery of the same message is
deduplicated and the group member receives no reply at all.

The optional ``dingtalk_stream`` SDK is stubbed by the streaming-card suite, so
that stub is reused here instead of copied a fourth time.
"""
import time
from types import SimpleNamespace

from bridge.context import ContextType
from tests.test_dingtalk_streaming_cards import _bare_channel, _context


def _group_channel(monkeypatch, composed):
    """A DingTalk channel whose context composition is fully controlled."""
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {})
    monkeypatch.setattr("common.time_check.config.conf", lambda: {"chat_time_module": False})

    ch = _bare_channel()
    ch.receivedMsgs = {}
    produced = []
    ch.produce = produced.append
    ch._compose_context = lambda *args, **kwargs: composed
    return ch, produced


def _group_message(msg_id="msg-1", content="hello"):
    return SimpleNamespace(
        ctype=ContextType.TEXT,
        content=content,
        msg_id=msg_id,
        create_time=str(int(time.time())),
        my_msg=False,
        is_group=True,
        other_user_id=f"conv-{msg_id}",
        from_user_id="staff-1",
    )


def test_group_message_without_a_context_is_skipped(monkeypatch):
    """A non-whitelisted group yields ``None``: skip it, do not raise, do not reply."""
    ch, produced = _group_channel(monkeypatch, None)

    ch.handle_group(_group_message())

    assert produced == []


def test_whitelisted_group_message_still_marks_no_need_at(monkeypatch):
    """Control: the guarded path keeps setting ``no_need_at`` and produces the turn."""
    context = _context(isgroup=True)
    ch, produced = _group_channel(monkeypatch, context)

    ch.handle_group(_group_message(msg_id="msg-2"))

    assert produced == [context]
    assert context["no_need_at"] is True
