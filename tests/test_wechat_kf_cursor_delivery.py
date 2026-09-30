from unittest.mock import Mock

import pytest

from bridge.context import ContextType
from channel.wechat_kf import wechat_kf_channel


class FakeMessage:
    def __init__(self, msg, client):
        self.ctype = ContextType.TEXT
        self.from_user_id = msg["external_userid"]
        self.content = msg["text"]["content"]


def make_channel(monkeypatch, pages):
    channel_class = wechat_kf_channel.WechatKfChannel.__wrapped__
    channel = channel_class.__new__(channel_class)
    channel.client = Mock()
    channel.cursor_store = Mock()
    channel.cursor_store.get.return_value = "cursor-before"
    channel._call_sync_msg = Mock(side_effect=pages)
    channel._compose_context = Mock(return_value=object())
    channel.produce = Mock()
    monkeypatch.setattr(wechat_kf_channel, "WechatKfMessage", FakeMessage)
    monkeypatch.setattr(wechat_kf_channel, "get_file_cache", lambda: Mock(get=lambda *_: []))
    monkeypatch.setattr(wechat_kf_channel.time, "sleep", lambda *_: None)
    return channel


def one_message_page(cursor="cursor-after", has_more=False):
    return {
        "msg_list": [
            {
                "external_userid": "user-1",
                "msgtype": "text",
                "text": {"content": "hello"},
            }
        ],
        "next_cursor": cursor,
        "has_more": has_more,
    }


def test_failed_delivery_does_not_advance_cursor(monkeypatch):
    channel = make_channel(monkeypatch, [one_message_page()])
    channel.produce.side_effect = RuntimeError("agent dispatch failed")

    with pytest.raises(RuntimeError, match="dispatch failed"):
        channel.consume_callback("token", "kf-1")

    channel.cursor_store.set.assert_not_called()


def test_failed_delivery_keeps_pending_attachments_for_retry(monkeypatch):
    channel = make_channel(monkeypatch, [one_message_page()])
    file_cache = Mock()
    file_cache.get.return_value = [{"type": "image", "path": "/tmp/photo.png"}]
    monkeypatch.setattr(wechat_kf_channel, "get_file_cache", lambda: file_cache)
    channel.produce.side_effect = RuntimeError("agent dispatch failed")

    with pytest.raises(RuntimeError, match="dispatch failed"):
        channel.consume_callback("token", "kf-1")

    assert "[图片: /tmp/photo.png]" in channel._compose_context.call_args.args[1]
    file_cache.clear.assert_not_called()
    channel.cursor_store.set.assert_not_called()


def test_cursor_advances_after_delivery_returns(monkeypatch):
    channel = make_channel(monkeypatch, [one_message_page()])

    def produce(_context):
        channel.cursor_store.set.assert_not_called()

    channel.produce.side_effect = produce

    channel.consume_callback("token", "kf-1")

    channel.produce.assert_called_once()
    channel.cursor_store.set.assert_called_once_with("kf-1", "cursor-after")


def test_pending_attachments_clear_after_successful_delivery(monkeypatch):
    channel = make_channel(monkeypatch, [one_message_page()])
    file_cache = Mock()
    file_cache.get.return_value = [{"type": "image", "path": "/tmp/photo.png"}]
    monkeypatch.setattr(wechat_kf_channel, "get_file_cache", lambda: file_cache)

    def produce(_context):
        file_cache.clear.assert_not_called()

    channel.produce.side_effect = produce

    channel.consume_callback("token", "kf-1")

    file_cache.clear.assert_called_once_with("user-1")
    channel.cursor_store.set.assert_called_once_with("kf-1", "cursor-after")


def test_filtered_messages_still_advance_cursor(monkeypatch):
    page = {
        "msg_list": [{"msgtype": "text", "text": {"content": "our own reply"}}],
        "next_cursor": "cursor-after",
        "has_more": False,
    }
    channel = make_channel(monkeypatch, [page])

    channel.consume_callback("token", "kf-1")

    channel.produce.assert_not_called()
    channel.cursor_store.set.assert_called_once_with("kf-1", "cursor-after")


def test_partial_pagination_commits_only_the_last_successful_page(monkeypatch):
    channel = make_channel(monkeypatch, [one_message_page("cursor-page-1", True), None])

    channel.consume_callback("token", "kf-1")

    channel.produce.assert_called_once()
    channel.cursor_store.set.assert_called_once_with("kf-1", "cursor-page-1")
