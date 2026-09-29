import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bridge.context import Context, ContextType
from channel.chat_channel import ChatChannel
from channel.feishu import feishu_channel
from channel.feishu.feishu_channel import FeishuController, FeiShuChanel
from common.dequeue import Dequeue
from common.expired_dict import ExpiredDict


def _context(message_id: str) -> Context:
    return Context(
        ContextType.TEXT,
        message_id,
        {
            "session_id": "session-1",
            "msg": SimpleNamespace(msg_id=message_id),
        },
    )


def _bare_chat_channel(*contexts: Context) -> ChatChannel:
    channel = ChatChannel.__new__(ChatChannel)
    channel.lock = threading.RLock()
    channel.futures = {}
    queue = Dequeue()
    for context in contexts:
        queue.put(context)
    channel.sessions = {"session-1": [queue, MagicMock()]}
    return channel


def test_cancel_message_removes_only_recalled_queued_context(monkeypatch):
    channel = _bare_chat_channel(_context("m1"), _context("m2"), _context("m3"))
    registry = MagicMock()
    registry.cancel_request.return_value = False
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)

    queued, active = channel.cancel_message("session-1", "m2")

    assert (queued, active) == (1, False)
    remaining = channel.sessions["session-1"][0]
    assert [remaining.get_nowait().get("msg").msg_id for _ in range(2)] == ["m1", "m3"]
    registry.cancel_request.assert_called_once_with("m2")


def test_cancel_message_targets_active_request_without_clearing_queue(monkeypatch):
    channel = _bare_chat_channel(_context("later"))
    registry = MagicMock()
    registry.cancel_request.return_value = True
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)

    queued, active = channel.cancel_message("session-1", "active")

    assert (queued, active) == (0, True)
    remaining = channel.sessions["session-1"][0]
    assert remaining.get_nowait().get("msg").msg_id == "later"


def test_feishu_message_uses_message_id_for_precise_recall(monkeypatch):
    channel = FeiShuChanel()
    channel.receivedMsgs = ExpiredDict(60)
    channel._message_sessions = ExpiredDict(60)
    monkeypatch.setattr(channel, "fetch_access_token", lambda: "tenant-token")
    monkeypatch.setattr(channel, "_make_feishu_stream_callback", lambda *_: MagicMock())
    produced = []
    monkeypatch.setattr(channel, "produce", produced.append)

    channel._handle_message_event(
        {
            "app_id": "cli_bot",
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "om_recall_me",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
                "message_type": "text",
                "create_time": str(int(time.time() * 1000)),
                "content": json.dumps({"text": "long task"}),
            },
        }
    )

    assert len(produced) == 1
    assert produced[0]["request_id"] == "om_recall_me"
    assert channel._message_sessions.get("om_recall_me") == "ou_user"


def test_feishu_recall_cancels_only_the_original_message(monkeypatch):
    channel = FeiShuChanel()
    channel._message_sessions = ExpiredDict(60)
    channel._message_sessions["om_recalled"] = "session-1"
    cancel_message = MagicMock(return_value=(0, True))
    monkeypatch.setattr(channel, "cancel_message", cancel_message)

    result = channel._handle_message_recalled_event(
        {"message_id": "om_recalled", "chat_id": "oc_chat"}
    )

    assert result == (0, True)
    cancel_message.assert_called_once_with("session-1", "om_recalled")
    assert channel._message_sessions.get("om_recalled") is None


def test_feishu_recall_ignores_unknown_message():
    channel = FeiShuChanel()
    channel._message_sessions = ExpiredDict(60)

    assert channel._handle_message_recalled_event({"message_id": "unknown"}) == (0, False)


def test_feishu_webhook_routes_message_recall(monkeypatch):
    channel = FeiShuChanel()
    channel.feishu_token = "verification-token"
    handle_recall = MagicMock(return_value=(1, False))
    monkeypatch.setattr(channel, "_handle_message_recalled_event", handle_recall)
    event = {"message_id": "om_recalled", "chat_id": "oc_chat"}
    request = {
        "header": {
            "event_type": "im.message.recalled_v1",
            "token": "verification-token",
        },
        "event": event,
    }
    monkeypatch.setattr(
        feishu_channel.web,
        "data",
        lambda: json.dumps(request).encode("utf-8"),
    )

    assert json.loads(FeishuController().POST()) == {"success": True}
    handle_recall.assert_called_once_with(event)


@pytest.mark.parametrize(
    ("configured_token", "header"),
    [
        ("", {"event_type": "im.message.recalled_v1"}),
        (None, {"event_type": "im.message.recalled_v1"}),
        ("verification-token", {"event_type": "im.message.recalled_v1"}),
        ("verification-token", {"event_type": "im.message.recalled_v1", "token": "wrong"}),
        ("verification-token", {"event_type": "im.message.recalled_v1", "token": 123}),
    ],
)
def test_feishu_webhook_rejects_invalid_token(monkeypatch, configured_token, header):
    channel = FeiShuChanel()
    channel.feishu_token = configured_token
    handle_recall = MagicMock()
    monkeypatch.setattr(channel, "_handle_message_recalled_event", handle_recall)
    request = {"header": header, "event": {"message_id": "om_forged"}}
    monkeypatch.setattr(
        feishu_channel.web,
        "data",
        lambda: json.dumps(request).encode("utf-8"),
    )

    assert json.loads(FeishuController().POST()) == {"success": False}
    handle_recall.assert_not_called()
