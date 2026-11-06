"""Plain-text channels drop the ** of bold text but keep code as written.

The WeCom app, WeChat Customer Service and Official Account (passive reply)
channels show replies as plain text, so ``remove_markdown_symbol`` removes the
** around bold text (#2344). It paired any two ** on a line, including those
in code blocks, in inline code and in the ** operator, so a reply's
``{**defaults, **overrides}`` reached the user as ``{defaults, overrides}``
and ``print(2 ** 10, 3 ** 4)`` as ``print(2  10, 3  4)``.
"""

from collections import defaultdict
from types import SimpleNamespace

import pytest

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.wechat_kf.wechat_kf_channel import WechatKfChannel
from channel.wechatcom.wechatcomapp_channel import WechatComAppChannel
from channel.wechatmp.wechatmp_channel import WechatMPChannel
from common.utils import remove_markdown_symbol

CODE = (
    "merged = {**defaults, **overrides}\n"
    "print(2 ** 10, 3 ** 4)\n"
    "distance = (dx**2 + dy**2) ** 0.5\n"
    "def call(*args, **kwargs): return target(*args, **kwargs)"
)

REPLY = f"**示例**：\n\n```python\n{CODE}\n```\n\n合并字典也可以写成 `dict(**defaults, **overrides)`。"
SENT = REPLY.replace("**示例**", "示例")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("**健康方面：**\n\n* 注意肠胃健康", "健康方面：\n\n* 注意肠胃健康", id="bold-line"),
        pytest.param("**注意**：先备份数据", "注意：先备份数据", id="bold-words"),
        pytest.param("- **第一步**：安装\n- **第二步**：运行", "- 第一步：安装\n- 第二步：运行", id="bold-in-list"),
        pytest.param("1. **`config.json`**：配置文件", "1. `config.json`：配置文件", id="bold-inline-code"),
        pytest.param("**用 `{**a, **b}` 合并**", "用 `{**a, **b}` 合并", id="bold-around-code-with-stars"),
        pytest.param("2 ** 10 等于 **1024**", "2 ** 10 等于 1024", id="operator-then-bold"),
        pytest.param("**注意 **重要** 事项**", "注意 重要 事项", id="bold-inside-bold"),
        pytest.param("**Note**: **Back up** first", "Note: Back up first", id="bold-after-colon"),
    ],
)
def test_bold_markers_are_removed(text, expected):
    assert remove_markdown_symbol(text) == expected


def test_closing_marker_pairs_with_the_nearest_opening_one():
    # As in Markdown, "**a **b**" is a literal "**a " followed by bold "b".
    assert remove_markdown_symbol("**注意 **重要**") == "**注意 重要"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("**Note: **Important", "Note: Important", id="colon"),
        pytest.param("**發布日期： **2026 年 7 月 30 日", "發布日期： 2026 年 7 月 30 日", id="full-width-colon"),
        pytest.param(
            "**发布日期： **2026 年 7 月 30 日\n**版本： **v2.2.2",
            "发布日期： 2026 年 7 月 30 日\n版本： v2.2.2",
            id="two-lines",
        ),
        pytest.param("**Note:\t**Important", "Note:\tImportant", id="tab"),
    ],
)
def test_bold_closed_after_a_colon_and_a_space_is_removed(text, expected):
    # Models write labels as "**Note: **text", with the space inside the bold.
    assert remove_markdown_symbol(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("**Important: **really** important**", "Important: really important", id="colon"),
        pytest.param("**注意： **重要** 事项**", "注意： 重要 事项", id="full-width-colon"),
    ],
)
def test_bold_inside_bold_after_a_colon_is_removed(text, expected):
    # The colon only counts for a ** that nothing else on the line pairs with,
    # so the inner ** still pair with each other and the outer ** too.
    assert remove_markdown_symbol(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("{**a, **b}: **Python 3.5+**", "{**a, **b}: Python 3.5+", id="dict-unpacking"),
        pytest.param("2**10: **1024**", "2**10: 1024", id="power"),
    ],
)
def test_operator_before_bold_after_a_colon_is_kept(text, expected):
    # The ** after the colon opens the bold that follows it, so it doesn't close
    # an earlier ** at the operator.
    assert remove_markdown_symbol(text) == expected


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_code_blocks_are_kept_as_written(fence):
    text = f"**合并字典**：\n\n{fence}python\n{CODE}\n{fence}\n\n**完成**"

    assert remove_markdown_symbol(text) == f"合并字典：\n\n{fence}python\n{CODE}\n{fence}\n\n完成"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Use `{**a, **b}` to merge two dicts", id="dict-merge"),
        pytest.param("使用 `**kwargs` 接收关键字参数，用 `**` 解包字典", id="kwargs-and-unpacking"),
        pytest.param("``f(**a) + `x` + g(**b)``", id="double-backtick-span"),
    ],
)
def test_inline_code_is_kept_as_written(text):
    assert remove_markdown_symbol(text) == text


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("x ** 2 + y ** 2 = z ** 2", id="formula"),
        pytest.param("print(2 ** 10, 3 ** 4)", id="power"),
        pytest.param("merged = {**defaults, **overrides}", id="dict-unpacking"),
        pytest.param("def f(*args, **kwargs): return g(*args, **kwargs)", id="kwargs-forwarding"),
    ],
)
def test_operators_outside_code_are_kept(text):
    # Bold opens only on a ** followed by a non-space character and closes
    # only on a ** preceded by one or by a colon and spaces.
    assert remove_markdown_symbol(text) == text


def _bare(channel_class):
    # @singleton exposes the undecorated class as __wrapped__; __new__ skips
    # __init__, which needs live credentials.
    cls = channel_class.__wrapped__
    return cls.__new__(cls)


def test_wecom_app_sends_code_as_written():
    sent = []
    channel = _bare(WechatComAppChannel)
    channel.agent_id = "1000002"
    channel.client = SimpleNamespace(
        message=SimpleNamespace(send_text=lambda agent_id, receiver, text: sent.append(text))
    )

    channel.send(Reply(ReplyType.TEXT, REPLY), Context(kwargs={"receiver": "user-1"}))

    assert sent == [SENT]


def test_wechat_kf_sends_code_as_written():
    payloads = []
    channel = _bare(WechatKfChannel)
    channel._post_send_msg = payloads.append
    context = Context(kwargs={"receiver": "user-1", "external_userid": "ext-1", "open_kfid": "kf-1"})

    channel.send(Reply(ReplyType.TEXT, REPLY), context)

    assert [payload["text"]["content"] for payload in payloads] == [SENT]


def test_official_account_caches_code_as_written():
    channel = _bare(WechatMPChannel)
    channel.passive_reply = True
    channel.cache_dict = defaultdict(list)

    channel.send(Reply(ReplyType.TEXT, REPLY), Context(kwargs={"receiver": "user-1"}))

    assert channel.cache_dict["user-1"] == [("text", SENT)]
