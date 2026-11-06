"""Long replies keep their code blocks when they are sent as several messages.

Telegram, Discord and Slack send a reply over their message size limit as
several messages, cut at line breaks. A cut inside a fenced code block left the
opening fence in one message and the closing fence in a later one, so the code
in between reached the user as text: Telegram showed ```python literally and
rendered ``__init__`` as a bold "init", and Discord's middle messages had no
fence at all.
"""

import asyncio
import re
import threading
from types import SimpleNamespace

import pytest

from bridge.reply import Reply, ReplyType
from channel.discord.discord_channel import DISCORD_MSG_LIMIT, DiscordChannel
from channel.slack.slack_channel import SlackChannel
from channel.telegram.telegram_channel import TelegramChannel
from channel.telegram.telegram_markdown import to_telegram_html
from common import markdown_fence

CODE = "\n".join(
    [
        "class Cache:",
        "    def __init__(self, size):",
        "        # keep the newest items",
        "        self.size = size",
        "        self.items = {}",
        "",
    ]
    * 40
)
REPLY = (
    "Here is the script.\n\n"
    + "Some explanation of the approach. " * 40
    + "\n\n```python\n"
    + CODE
    + "\n```\n\nThat's it.\n"
)
FENCE_LINE = re.compile(r"^[ \t]*(?:`{3,}|~{3,})")


def _fence_lines(message):
    return [line.strip() for line in message.split("\n") if FENCE_LINE.match(line)]


@pytest.mark.parametrize("limit", [4000, 1900, 3500], ids=["telegram", "discord", "slack"])
def test_code_block_cut_between_chunks_is_closed_and_reopened(limit):
    chunks = list(markdown_fence.split_markdown(REPLY, limit))

    assert len(chunks) > 1
    assert all(len(chunk) <= limit for chunk in chunks)
    assert [_fence_lines(chunk) for chunk in chunks] == [["```python", "```"]] * len(chunks)
    # Only the added fence lines differ from the reply.
    assert "".join(chunks).replace("```\n```python\n", "") == REPLY


@pytest.mark.parametrize(
    ("opening", "body", "closing", "lang"),
    [
        pytest.param("~~~yaml", "key: value", "~~~", "yaml", id="tilde"),
        pytest.param("````markdown", "```\nx = 1\n```", "````", "markdown", id="longer-fence"),
        pytest.param("  ```js", "  let x = 1;", "  ```", "js", id="indented"),
    ],
)
def test_block_is_reopened_with_its_own_fence_lines(opening, body, closing, lang):
    text = "\n".join([opening] + [body] * 30 + [closing]) + "\n"

    chunks = list(markdown_fence.split_markdown(text, 120))

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 120
        assert chunk.startswith(opening + "\n") and chunk.endswith("\n" + closing + "\n")
        html = to_telegram_html(chunk)
        assert html.startswith(f'<pre><code class="language-{lang}">') and html.count("<pre>") == 1
    assert "".join(chunks).replace(f"{closing}\n{opening}\n", "") == text


def test_code_line_longer_than_the_limit_is_cut_inside_the_block():
    chunks = list(markdown_fence.split_markdown("```\n" + "x" * 50 + "\n```", 20))

    assert chunks == ["```\n" + "x" * 12 + "\n```"] * 4 + ["```\nxx\n```"]


def test_chunk_does_not_end_on_an_opening_fence():
    text = "a" * 14 + "\n```\nb\n```"

    assert list(markdown_fence.split_markdown(text, 20)) == ["a" * 14 + "\n", "```\nb\n```"]


# Text is cut at line breaks as before; a block that fits in a chunk and an
# unclosed fence are cut like any other text.
@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        pytest.param("short", 5, ["short"], id="within-limit"),
        pytest.param("one\ntwo\nthree\n", 8, ["one\ntwo\n", "three\n"], id="lines"),
        pytest.param("x" * 10 + "\ny", 4, ["xxxx", "xxxx", "xx\ny"], id="long-line"),
        pytest.param(
            "a" * 10 + "\n```py\nx = 1\n```\n" + "b" * 10,
            30,
            ["a" * 10 + "\n```py\nx = 1\n```\n", "b" * 10],
            id="block-within-a-chunk",
        ),
        pytest.param(
            "```python\n" + "x = 1\n" * 10,
            20,
            ["```python\nx = 1\n"] + ["x = 1\n" * 3] * 3,
            id="unclosed-fence",
        ),
    ],
)
def test_text_not_cut_inside_a_block_splits_at_line_breaks(text, limit, expected):
    assert list(markdown_fence.split_markdown(text, limit)) == expected


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


class _TelegramBot:
    def __init__(self):
        self.texts = []

    async def send_message(self, chat_id, text, **kwargs):
        self.texts.append(text)


def test_telegram_renders_every_part_of_the_block_as_code(loop):
    bot = _TelegramBot()
    channel = TelegramChannel.__wrapped__.__new__(TelegramChannel.__wrapped__)
    channel._loop, channel._bot = loop, bot

    channel.send(Reply(ReplyType.TEXT, REPLY), {"telegram_chat_id": 42})

    assert len(bot.texts) == 2
    for html in bot.texts:
        assert html.count('<pre><code class="language-python">') == 1
        assert "```" not in html and "<b>init</b>" not in html


def test_discord_sends_every_part_of_the_block_in_a_code_block(loop):
    sent = []

    async def send(content):
        sent.append(content)

    channel = DiscordChannel.__wrapped__.__new__(DiscordChannel.__wrapped__)
    channel._loop = loop
    channel._client = SimpleNamespace(get_channel=lambda _id: SimpleNamespace(send=send))

    channel.send(Reply(ReplyType.TEXT, REPLY), {"discord_channel_id": 1})

    assert len(sent) == 4
    assert all(len(message) <= DISCORD_MSG_LIMIT for message in sent)
    assert [_fence_lines(message) for message in sent] == [["```python", "```"]] * 4


def test_slack_sends_every_part_of_the_block_in_a_code_block():
    sent = []
    channel = SlackChannel.__wrapped__.__new__(SlackChannel.__wrapped__)
    channel._client = SimpleNamespace(chat_postMessage=lambda **kwargs: sent.append(kwargs["text"]))

    channel.send(Reply(ReplyType.TEXT, REPLY), {"slack_channel": "C1"})

    assert len(sent) == 2
    assert all(len(message) <= 3500 for message in sent)
    assert [_fence_lines(message) for message in sent] == [["```python", "```"]] * 2
