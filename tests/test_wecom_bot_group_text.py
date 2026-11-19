"""A WeCom group message keeps every "@" in its text except the bot's mention.

WeCom only pushes a group message to the bot when the bot is @-mentioned in it,
and the mention is plain text in the message: the "receive message" docs show
``"@RobotA hello robot"`` for a text message and ``"@机器人 这是今日的测试情况"``
for the text of a mixed one. The message carries no mention list and no bot
name, so the "@name" that opens the text is taken as the bot's or, when none
does, one that ends it, as when a member types a command before the mention
(``/cancel @CowAgent``).

WecomBotMessage used to delete every "@" in a group message together with the
non-space characters after it. The agent got e-mail addresses cut down to the
part before the "@", links holding an "@" cut short, other members' mentions
dropped and decorators or scoped npm packages deleted, with nothing logged. A
team member named after the bot ("@CowAgent @Ops ...") was deleted as well, so
it never took the turn as docs/multi-agent/team.mdx describes.
"""
import json
import os
import threading
from types import SimpleNamespace

import pytest

import config
import plugins
from channel.wecom_bot import wecom_bot_message
from channel.wecom_bot.wecom_bot_message import WecomBotMessage
from plugins import Event, EventContext

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    import plugins.cow_cli.cow_cli  # noqa: F401
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

CowCliPlugin = plugins.instance.plugins["COW_CLI"]

# What a member typed before or after "@CowAgent"; each one has an "@" of its own.
TEXTS = [
    pytest.param("把周报发到 zhang.san@example.com", id="email"),
    pytest.param("总结一下 https://medium.com/@karpathy/software-2-0-a64152b37c35", id="link"),
    pytest.param("克隆 git@github.com:zhayujie/CowAgent.git 看看", id="git-url"),
    pytest.param("提醒 @李四 明天交周报", id="member-mention"),
    pytest.param("Python 里 @staticmethod 和 @classmethod 有什么区别", id="decorators"),
    pytest.param("npm install @types/node 报错了", id="scoped-package"),
]

IMAGE = {"msgtype": "image", "image": {"url": "https://example.com/image", "aeskey": ""}}


def _body(content, msgtype="text", chattype="group"):
    body = {
        "msgid": "msg-1",
        "aibotid": "bot-1",
        "chatid": "chat-1",
        "chattype": chattype,
        "from": {"userid": "user-1"},
        "msgtype": msgtype,
    }
    if msgtype == "mixed":
        body["mixed"] = {"msg_item": content}
    else:
        body[msgtype] = {"content": content}
    return body


def _text_item(content):
    return {"msgtype": "text", "text": {"content": content}}


@pytest.mark.parametrize("text", TEXTS)
def test_a_group_text_keeps_everything_after_the_bot_mention(text):
    msg = WecomBotMessage(_body("@CowAgent " + text), is_group=True)

    assert msg.content == text


@pytest.mark.parametrize("text", TEXTS)
def test_a_group_text_keeps_everything_before_a_closing_bot_mention(text):
    msg = WecomBotMessage(_body(text + " @CowAgent"), is_group=True)

    assert msg.content == text


@pytest.mark.parametrize("text", [
    pytest.param("#help", id="godcmd-command"),
    pytest.param("帮我查下天气", id="question"),
])
def test_a_bot_mention_that_ends_the_message_is_removed(text):
    """A member can type the request first and the mention after it."""
    msg = WecomBotMessage(_body(text + " @CowAgent"), is_group=True)

    assert msg.content == text


def test_a_closing_mention_stays_when_the_bot_mention_opens_the_message():
    msg = WecomBotMessage(_body("@CowAgent 提醒一下 @李四"), is_group=True)

    assert msg.content == "提醒一下 @李四"


@pytest.mark.parametrize("text", [
    pytest.param("@CowAgent" + chr(0x2005) + "hello", id="opening"),
    pytest.param("hello" + chr(0x2005) + "@CowAgent", id="closing"),
])
def test_a_mention_next_to_a_four_per_em_space_is_removed_too(text):
    msg = WecomBotMessage(_body(text), is_group=True)

    assert msg.content == "hello"


def test_a_direct_message_is_kept_as_typed():
    text = "@staticmethod 和 @classmethod 有什么区别"
    msg = WecomBotMessage(_body(text, chattype="single"), is_group=False)

    assert msg.content == text


@pytest.fixture
def media_dir(monkeypatch, tmp_path):
    """Images of a mixed message 'download' into tmp_path."""
    monkeypatch.setattr(wecom_bot_message, "_decrypt_media", lambda url, aeskey: b"image bytes")
    monkeypatch.setattr(wecom_bot_message, "_get_tmp_dir", lambda: str(tmp_path))
    return tmp_path


def test_a_mixed_group_message_keeps_the_text_after_the_bot_mention(media_dir):
    items = [_text_item("@CowAgent 把这张图发给 li.si@example.com"), IMAGE]
    msg = WecomBotMessage(_body(items, msgtype="mixed"), is_group=True)

    assert msg.content.split("\n") == [
        "把这张图发给 li.si@example.com",
        f"[图片: {media_dir / 'wecom_msg-1_1.png'}]",
    ]


def test_a_mixed_group_message_can_end_with_the_bot_mention(media_dir):
    items = [_text_item("把这张图发给 li.si@example.com"), IMAGE, _text_item("@CowAgent")]
    msg = WecomBotMessage(_body(items, msgtype="mixed"), is_group=True)

    assert msg.content.split("\n") == [
        "把这张图发给 li.si@example.com",
        f"[图片: {media_dir / 'wecom_msg-1_1.png'}]",
    ]


def test_only_the_first_text_of_a_mixed_message_opens_with_the_bot_mention(media_dir):
    items = [_text_item("@CowAgent"), IMAGE, _text_item("@李四 你看这张图")]
    msg = WecomBotMessage(_body(items, msgtype="mixed"), is_group=True)

    assert msg.content.split("\n")[0] == "@李四 你看这张图"


@pytest.fixture
def wecom_channel(monkeypatch):
    """A WecomBotChannel without a connection; produce() records the contexts."""
    import channel.file_cache as cache_module
    from channel.channel import Channel
    from channel.wecom_bot import wecom_bot_channel as module
    from common.expired_dict import ExpiredDict

    cls = module.WecomBotChannel.__wrapped__
    ch = cls.__new__(cls)
    Channel.__init__(ch)
    ch.channel_type = "wecom_bot"
    ch.received_msgs = ExpiredDict(3600)
    ch._callback_streams = ExpiredDict(600)
    ch._callback_lock = threading.Lock()
    ch.produced = []
    ch.produce = ch.produced.append
    monkeypatch.setattr(module, "conf", lambda: {"image_create_prefix": []})
    cache = cache_module.FileCache()
    monkeypatch.setattr(cache_module, "get_file_cache", lambda: cache)
    return ch


def _receive(channel, text):
    """A group text message through the websocket receive path."""
    channel._handle_msg_callback({"headers": {"req_id": ""}, "body": _body(text)})


@pytest.mark.parametrize("mode", ["websocket", "webhook"])
def test_the_agent_gets_the_whole_request(wecom_channel, mode):
    body = _body("@CowAgent 把周报发到 zhang.san@example.com")
    if mode == "websocket":
        wecom_channel._handle_msg_callback({"headers": {"req_id": ""}, "body": body})
    else:
        wecom_channel._callback_handle_message(body)

    assert [context.content for context in wecom_channel.produced] == ["把周报发到 zhang.san@example.com"]


@pytest.fixture
def config_json(monkeypatch, tmp_path):
    """The config.json that /config writes, in a data dir of its own."""
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    # /config reloads the config after writing it; keep the suite's own.
    monkeypatch.setattr(config, "load_config", lambda: None)
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    return path


@pytest.mark.parametrize("command, key, value", [
    pytest.param("/config model gpt-4o", "model", "gpt-4o", id="model"),
    pytest.param("/config enable_thinking false", "enable_thinking", False, id="enable_thinking"),
])
def test_a_config_command_typed_before_the_bot_mention_saves_the_value(
    wecom_channel, config_json, command, key, value
):
    _receive(wecom_channel, command + " @CowAgent")
    [context] = wecom_channel.produced
    event = EventContext(
        Event.ON_HANDLE_CONTEXT, {"context": context, "reply": None, "channel": wecom_channel}
    )

    CowCliPlugin().on_handle_context(event)

    assert json.loads(config_json.read_text(encoding="utf-8"))[key] == value


def test_a_cancel_command_typed_before_the_bot_mention_skips_the_queue(wecom_channel, monkeypatch):
    """Queued, /cancel would wait for the very turn it has to stop."""
    router = SimpleNamespace(
        route_context=lambda context: "default",
        agent_registry=SimpleNamespace(default_agent_id="default"),
        _cancel_key=lambda agent_id, session_id, default_agent_id: session_id,
    )
    monkeypatch.setattr("bridge.bridge.Bridge", lambda: SimpleNamespace(get_agent_bridge=lambda: router))
    del wecom_channel.produce  # the real ChatChannel.produce, with its /cancel fast path
    wecom_channel.sessions, wecom_channel.lock = {}, threading.Lock()
    cancelled = []
    wecom_channel._handle_cancel_command = lambda context, session_id: cancelled.append(context.content)

    _receive(wecom_channel, "/cancel @CowAgent")

    assert cancelled == ["/cancel"]
    assert wecom_channel.sessions == {}, "/cancel must not be queued"


@pytest.fixture
def team_channel(wecom_channel, tmp_path):
    """The channel instance is bound to the CowAgent Agent, with Ops on its team."""
    from agent.registry import AgentProfile, AgentRegistry, set_agent_registry

    set_agent_registry(AgentRegistry(
        [
            AgentProfile(id="agent-abc", name="CowAgent", workspace=str(tmp_path / "cow")),
            AgentProfile(id="ops", name="Ops", workspace=str(tmp_path / "ops")),
        ],
        "agent-abc",
    ))
    wecom_channel.apply_instance(bound_agent_id="agent-abc", members=["ops"])
    yield wecom_channel
    # None, not an instance: pinning one back would outlive the test.
    set_agent_registry(None)


def test_a_teammate_named_after_the_bot_mention_takes_the_turn(team_channel):
    _receive(team_channel, "@CowAgent @Ops 查一下日志")

    [context] = team_channel.produced
    assert context.content == "@Ops 查一下日志"
    assert context.get("speaker_agent_id") == "ops"
