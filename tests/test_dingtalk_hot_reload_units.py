# encoding:utf-8
"""DingTalk hot_reload history filter compares milliseconds with seconds.

``cmsg.create_time`` is the DingTalk event's ``create_at`` in milliseconds
(process() itself divides it by 1000 when logging). The _check history
filter compared it against ``time.time() - 60`` in *seconds*, so a
millisecond value (~1.7e12) was never smaller: the "skip messages older
than a minute" branch could not fire and stale history replays were
processed as fresh messages.
"""
import time

from bridge.context import ContextType
from tests.test_dingtalk_streaming_cards import _bare_channel


def _channel(monkeypatch, hot_reload):
    from channel.dingtalk import dingtalk_channel as mod

    monkeypatch.setattr(mod, "conf", lambda: {"hot_reload": hot_reload})
    ch = _bare_channel()
    ch.receivedMsgs = {}
    produced = []
    ch.produce = produced.append
    ch._compose_context = lambda *a, **k: object()
    return ch, produced


def _message(msg_id, create_time_ms):
    from types import SimpleNamespace

    return SimpleNamespace(
        ctype=ContextType.TEXT,
        content="hello",
        msg_id=msg_id,
        create_time=str(create_time_ms),
        my_msg=False,
        is_group=False,
        other_user_id="conv-1",
        from_user_id="staff-1",
    )


def test_history_message_is_skipped_under_hot_reload(monkeypatch):
    ch, produced = _channel(monkeypatch, hot_reload=True)
    old_ms = int((time.time() - 120) * 1000)  # two minutes ago, in ms

    ch.handle_single(_message("msg-old", old_ms))

    assert produced == [], "a message older than a minute must be skipped"


def test_fresh_message_still_processed_under_hot_reload(monkeypatch):
    ch, produced = _channel(monkeypatch, hot_reload=True)
    fresh_ms = int(time.time() * 1000)

    ch.handle_single(_message("msg-new", fresh_ms))

    assert len(produced) == 1


def test_history_filter_is_inert_without_hot_reload(monkeypatch):
    ch, produced = _channel(monkeypatch, hot_reload=False)
    old_ms = int((time.time() - 120) * 1000)

    ch.handle_single(_message("msg-old", old_ms))

    assert len(produced) == 1
