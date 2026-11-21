"""A group message must be addressed to the bot before the bot answers it.

An app holding the broad im:message scope receives every group message, so the
channel decides from the mention list whether a message is meant for it. A
rich-text (post) message carries text and @mentions just like a plain text one,
but used to skip that decision entirely.

Feishu delivers the events in ``event.message``; ``mentions`` is the list of
people the message @-named, and is empty when it names nobody.
"""
import json
import time
from unittest.mock import MagicMock

import pytest

from channel.channel_factory import create_channel
from channel.feishu.feishu_channel import FeiShuChanel
from config import conf

BOT_OPEN_ID = "ou_bot"
OTHER_OPEN_ID = "ou_other"


@pytest.fixture(autouse=True)
def skip_websocket_sdk(monkeypatch):
    # These tests exercise the event handler shared by both transports.
    monkeypatch.setattr("channel.feishu.feishu_channel._ensure_lark_imported", lambda: None)


def _mentions(*open_ids):
    return [{"id": {"open_id": open_id}, "name": open_id} for open_id in open_ids]


def _event(message_type, mentions, message_id):
    if message_type == "text":
        content = json.dumps({"text": "hi"})
    else:
        content = json.dumps(
            {
                "title": "",
                "content": [
                    [
                        {"tag": "text", "text": "hi"},
                        {"tag": "at", "user_id": OTHER_OPEN_ID},
                    ]
                ],
            }
        )
    return {
        "app_id": "cli_bot",
        "sender": {"sender_id": {"open_id": "ou_user"}},
        "message": {
            "message_id": message_id,
            "chat_id": "oc_chat",
            "chat_type": "group",
            "message_type": message_type,
            "create_time": str(int(time.time() * 1000)),
            "content": content,
            "mentions": mentions,
        },
    }


@pytest.mark.parametrize(
    "message_type,mentions,answered",
    [
        pytest.param("text", _mentions(OTHER_OPEN_ID), False, id="text-mentions-others"),
        pytest.param("post", _mentions(OTHER_OPEN_ID), False, id="post-mentions-others"),
        pytest.param("text", [], False, id="text-silent"),
        pytest.param("post", [], False, id="post-silent"),
        pytest.param("text", _mentions(BOT_OPEN_ID), True, id="text-mentions-bot"),
        pytest.param("post", _mentions(BOT_OPEN_ID), True, id="post-mentions-bot"),
    ],
)
def test_group_messages_are_gated_on_the_bot_being_addressed(
    monkeypatch, message_type, mentions, answered
):
    channel = FeiShuChanel()
    monkeypatch.setattr(channel, "_bot_open_id", BOT_OPEN_ID)
    monkeypatch.setattr(channel, "fetch_access_token", lambda: "tenant-token")
    monkeypatch.setattr(channel, "_make_feishu_stream_callback", lambda *_: MagicMock())
    produced = []
    monkeypatch.setattr(channel, "produce", produced.append)

    # The channel is a singleton, so its received-ids set survives between cases
    # and a repeated message id is dropped as a duplicate before the gate runs.
    message_id = f"om_{message_type}-{len(mentions)}-{int(answered)}"
    channel._handle_message_event(_event(message_type, mentions, message_id))

    assert bool(produced) is answered


def test_unsupported_message_types_are_skipped_without_parsing(monkeypatch):
    # An interactive card posted by another bot in the group used to reach
    # FeishuMessage and raise NotImplementedError on every occurrence.
    channel = FeiShuChanel()
    monkeypatch.setattr(channel, "_bot_open_id", BOT_OPEN_ID)
    monkeypatch.setattr(channel, "fetch_access_token", lambda: "tenant-token")
    produced = []
    monkeypatch.setattr(channel, "produce", produced.append)

    def _fail(*_args, **_kwargs):
        raise AssertionError("unsupported message types must not be parsed")

    monkeypatch.setattr("channel.feishu.feishu_channel.FeishuMessage.__init__", _fail)
    event = _event("text", [], "om_interactive-card")
    event["message"]["message_type"] = "interactive"
    event["message"]["content"] = json.dumps({"title": "card", "elements": []})

    channel._handle_message_event(event)

    assert produced == []


@pytest.mark.parametrize(
    "global_enabled, instance_enabled, chat_type, answered",
    [
        pytest.param(None, None, "p2p", True, id="default-enabled"),
        pytest.param(False, None, "p2p", False, id="global-disabled"),
        pytest.param(True, False, "p2p", False, id="instance-disabled"),
        pytest.param(False, True, "p2p", True, id="instance-enabled"),
        pytest.param(False, False, "group", True, id="group-still-answers"),
    ],
)
def test_feishu_private_chat_setting(monkeypatch, global_enabled, instance_enabled, chat_type, answered):
    key = "feishu_private_chat_enabled"
    if global_enabled is None:
        monkeypatch.delitem(conf(), key, raising=False)
    else:
        monkeypatch.setitem(conf(), key, global_enabled)
    credentials = {} if instance_enabled is None else {key: instance_enabled}
    channel = create_channel("feishu", instance_id="feishu-test", credentials=credentials)
    monkeypatch.setattr(channel, "_bot_open_id", BOT_OPEN_ID)
    fetch_token = MagicMock(return_value="tenant-token")
    monkeypatch.setattr(channel, "fetch_access_token", fetch_token)
    monkeypatch.setattr(channel, "_make_feishu_stream_callback", lambda *_: MagicMock())
    produced = []
    monkeypatch.setattr(channel, "produce", produced.append)

    event = _event("text", _mentions(BOT_OPEN_ID), "om_private_chat_setting")
    event["message"]["chat_type"] = chat_type
    channel._handle_message_event(event)

    assert bool(produced) is answered
    assert fetch_token.called is answered


def test_private_messages_use_only_instance_owner_settings(monkeypatch):
    from channel.feishu.owner_config import MEMORY_MODE, OWNER_IDS

    monkeypatch.setitem(conf(), "feishu_app_id", "cli_old")
    monkeypatch.setitem(conf(), "feishu_owner_open_id", "ou_legacy")
    monkeypatch.setitem(conf(), MEMORY_MODE, "shared")
    bots = (
        (FeiShuChanel.new_instance(), "cli_old", [], "owner_workspace"),
        (create_channel("feishu", instance_id="bot-other"), "cli_other", [], "owner_workspace"),
        (create_channel("feishu", instance_id="bot-owner", credentials={
            "feishu_app_id": "cli_owner", OWNER_IDS: ["ou_a", "ou_b"], MEMORY_MODE: "per_user",
        }), "cli_owner", ["ou_a", "ou_b"], "per_user"),
    )
    for channel, app_id, owners, mode in bots:
        monkeypatch.setattr(channel, "feishu_app_id", app_id)
        monkeypatch.setattr(channel, "fetch_access_token", lambda: "tenant-token")
        monkeypatch.setattr(channel, "_make_feishu_stream_callback", lambda *_: MagicMock())
        produced = []
        monkeypatch.setattr(channel, "produce", produced.append)
        event = _event("text", [], f"om_{app_id}")
        event["app_id"] = app_id
        event["message"]["chat_type"] = "p2p"

        channel._handle_message_event(event)

        msg = produced[0]["msg"]
        assert msg.identity_owner_open_ids == owners
        assert msg.identity_private_memory_mode == mode
