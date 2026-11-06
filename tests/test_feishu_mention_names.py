"""The agent reads who a group message @-mentions, not Feishu's placeholders.

Feishu writes each mention in a text message as a placeholder numbered by
mention order (``@_user_1``, ``@_user_2``, ...) and lists who each one is in
the event's ``mentions``: ``{"key": "@_user_2", "id": {"open_id": ...},
"name": "张三"}``. A post (rich text) message carries the same keys in its
``at`` elements. The bot is one of those mentions, in whatever position it was
named, and only its own mention is left out of what the agent reads. A post
that carries files and says nothing besides its mentions is still cached until
the question comes, like a file sent on its own.
"""
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from channel import file_cache
from channel.feishu import feishu_message
from channel.feishu.feishu_channel import FeiShuChanel
from common.expired_dict import ExpiredDict
from config import conf

BOT = {"id": {"open_id": "ou_bot"}, "name": "CowAgent"}
ZHANG = {"id": {"open_id": "ou_zhang"}, "name": "张三"}
COLLEAGUES = [{"id": {"open_id": f"ou_{n}"}, "name": f"同事{n}"} for n in range(1, 11)]


def _mentions(*people):
    """The event's mention list: the n-th person mentioned has the key @_user_n."""
    return [dict(person, key=f"@_user_{n}") for n, person in enumerate(people, 1)]


def _event(message_type, content, mentions, chat_type="group"):
    message = {
        "message_id": "om_mention",
        "chat_id": "oc_chat",
        "chat_type": chat_type,
        "message_type": message_type,
        "create_time": str(int(time.time() * 1000)),
        "content": json.dumps(content, ensure_ascii=False),
    }
    if mentions is not None:
        message["mentions"] = mentions
    return {"app_id": "cli_bot", "sender": {"sender_id": {"open_id": "ou_sender"}}, "message": message}


def _at(key):
    return {"tag": "at", "user_id": key, "user_name": "", "style": []}


def _produced(monkeypatch, event, bot_open_id="ou_bot"):
    """Run the event through the channel and return the contexts handed to the agent."""
    channel = FeiShuChanel()
    # The channel is a singleton: give every case a fresh received-ids set so
    # the shared message id is not dropped as a duplicate.
    monkeypatch.setattr(channel, "receivedMsgs", ExpiredDict(60))
    monkeypatch.setattr(channel, "_bot_open_id", bot_open_id)
    monkeypatch.setattr(channel, "fetch_access_token", lambda: "tenant-token")
    monkeypatch.setattr(channel, "_make_feishu_stream_callback", lambda *_: MagicMock())
    produced = []
    monkeypatch.setattr(channel, "produce", produced.append)

    channel._handle_message_event(event)

    return produced


def _agent_input(monkeypatch, event, bot_open_id="ou_bot"):
    """Run the event through the channel and return the text handed to the agent."""
    produced = _produced(monkeypatch, event, bot_open_id)

    assert len(produced) == 1
    return produced[0].content


@pytest.mark.parametrize(
    "text,mentions,expected",
    [
        pytest.param(
            "@_user_1 提醒 @_user_2 明天交周报",
            _mentions(BOT, ZHANG),
            "提醒 @张三 明天交周报",
            id="bot-first",
        ),
        pytest.param(
            "@_user_1 @_user_2 总结一下他刚才的发言",
            _mentions(ZHANG, BOT),
            "@张三 总结一下他刚才的发言",
            id="colleague-first",
        ),
        pytest.param(
            "@_user_1 你提的问题 @_user_2 可以回答",
            _mentions(ZHANG, BOT),
            "@张三 你提的问题 可以回答",
            id="bot-mid-sentence",
        ),
        pytest.param(
            # @_user_10 and @_user_11 start with @_user_1, the bot's key.
            "@_user_1 通知 " + " ".join(f"@_user_{n}" for n in range(2, 12)) + " 下午开会",
            _mentions(BOT, *COLLEAGUES),
            "通知 " + " ".join(f"@同事{n}" for n in range(1, 11)) + " 下午开会",
            id="eleven-mentions",
        ),
        pytest.param(
            # A digit typed right after a key is text, not part of the key.
            "@_user_13点提醒我开会",
            _mentions(BOT),
            "3点提醒我开会",
            id="bot-key-followed-by-digit",
        ),
        pytest.param(
            "@_user_1 提醒 @_user_23点交周报",
            _mentions(BOT, ZHANG),
            "提醒 @张三3点交周报",
            id="colleague-key-followed-by-digit",
        ),
        pytest.param(
            "@_user_1 提醒 @_user_2 明天交周报",
            _mentions(BOT, dict(ZHANG, name="")),
            "提醒 @_user_2 明天交周报",
            id="nameless-mention-keeps-placeholder",
        ),
    ],
)
def test_group_text_names_the_people_it_mentions(monkeypatch, text, mentions, expected):
    event = _event("text", {"text": text}, mentions)

    assert _agent_input(monkeypatch, event) == expected


def test_group_post_names_the_people_it_mentions(monkeypatch):
    # "@CowAgent 把 **第三季度预算** 发给 @张三": the bold text makes it a post.
    post = {
        "title": "",
        "content": [
            [
                _at("@_user_1"),
                {"tag": "text", "text": " 把 ", "style": []},
                {"tag": "text", "text": "第三季度预算", "style": ["bold"]},
                {"tag": "text", "text": " 发给 ", "style": []},
                _at("@_user_2"),
            ]
        ],
    }
    event = _event("post", post, _mentions(BOT, ZHANG))

    # A post still puts each of its elements on a line of its own; compare the words.
    assert _agent_input(monkeypatch, event).split() == ["把", "第三季度预算", "发给", "@张三"]


def _group_post_with_file(monkeypatch, tmp_path, *elements):
    """A group post of these elements with report.pdf attached, and the file cache the channel uses."""
    def download(message_id, key, resource_type, access_token, path, max_bytes):
        Path(path).write_bytes(b"data")
        return True

    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(feishu_message, "_download_resource", download)
    cache = file_cache.FileCache()
    monkeypatch.setattr(file_cache, "get_file_cache", lambda: cache)
    monkeypatch.setitem(conf(), "group_shared_session", True)
    # A file sent with a caption: the attachment sits next to the post's content.
    post = {
        "title": "",
        "content": [list(elements)],
        "files": [{"file_key": "file_v3_report", "file_name": "report.pdf"}],
    }
    return _event("post", post, _mentions(BOT, ZHANG)), cache


def test_group_post_of_a_file_and_mentions_waits_for_the_question(monkeypatch, tmp_path):
    # "@CowAgent @张三" with a file attached says nothing besides the mentions,
    # so like a file sent on its own it is cached until the question comes.
    event, cache = _group_post_with_file(
        monkeypatch,
        tmp_path,
        _at("@_user_1"),
        {"tag": "text", "text": " ", "style": []},
        _at("@_user_2"),
    )

    assert _produced(monkeypatch, event) == []
    assert cache.get("oc_chat") == [{"path": str(tmp_path / "file_v3_report.pdf"), "type": "file"}]


def test_group_post_of_a_file_and_a_question_names_the_people_it_mentions(monkeypatch, tmp_path):
    # "@CowAgent 把这份报告发给 @张三" with a file attached is answered at once.
    event, _ = _group_post_with_file(
        monkeypatch,
        tmp_path,
        _at("@_user_1"),
        {"tag": "text", "text": " 把这份报告发给 ", "style": []},
        _at("@_user_2"),
    )

    lines = _agent_input(monkeypatch, event).split("\n")
    assert [line.strip() for line in lines] == [
        "把这份报告发给",
        "@张三",
        f"[文件: {tmp_path / 'file_v3_report.pdf'}]",
    ]


def test_bot_named_by_feishu_bot_name_is_left_out(monkeypatch):
    # Without the bot's open_id, the group gate matches the bot by feishu_bot_name.
    monkeypatch.setitem(conf(), "feishu_bot_name", "CowAgent")
    event = _event("text", {"text": "@_user_1 @_user_2 总结一下他刚才的发言"}, _mentions(ZHANG, BOT))

    assert _agent_input(monkeypatch, event, bot_open_id=None) == "@张三 总结一下他刚才的发言"


def test_direct_message_text_is_unchanged(monkeypatch):
    # A direct message is not gated on mentions and carries no mention list.
    event = _event("text", {"text": "明天提醒我交周报"}, None, chat_type="p2p")

    assert _agent_input(monkeypatch, event) == "明天提醒我交周报"
