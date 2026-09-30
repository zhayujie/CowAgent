# encoding:utf-8
"""``$mju``/``$mjv`` with a non-numeric image index must answer, not die.

``MJBot.process_mj_task`` parses ``$mju <图片ID> <图片序号>`` and reads the index
with a bare ``int(clist[1])`` (plugins/linkai/midjourney.py:161). The two
neighbouring mistakes a user can make on that argument -- a missing one and a
numeric one outside 1..4 -- both get a reply (lines 158 and 163), but a token
that is not a number at all raises ``ValueError`` out of ``on_handle_context``,
past the worker's ``_thread_pool_callback``, which only logs
(channel/chat_channel.py:452-453). The user's command then produces no message
of any kind.
"""

from unittest.mock import patch

import plugins
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from plugins import Event, EventContext

plugins.instance.current_plugin_path = "./plugins/linkai"
import plugins.linkai.midjourney as midjourney  # noqa: E402
plugins.instance.current_plugin_path = None

CONF = {
    "linkai_api_base": "https://api.example.test",
    "linkai_api_key": "test-key",
    "linkai_app_code": "",
    "plugin_trigger_prefix": "$",
}
CONFIG = {"enabled": True, "max_tasks": 5, "max_tasks_per_user": 3}


def _run(content):
    """Hand ``content`` to the task processor and report what came back."""
    context = Context(ContextType.TEXT, content)
    context["session_id"] = "u1"
    event = EventContext(
        Event.ON_HANDLE_CONTEXT, {"context": context, "reply": None}
    )
    # MJBot reads the global config in __init__, so the whole call has to live
    # inside the patch or the stub never reaches it.
    with patch.object(midjourney, "conf", lambda: CONF):
        bot = midjourney.MJBot(CONFIG, fetch_group_app_code=lambda _: None)
        bot.process_mj_task(midjourney.TaskType.UPSCALE, event)
    return event["reply"]


def test_non_numeric_index_gets_a_reply_instead_of_raising():
    # A trailing typo is the same class of user mistake as the two the command
    # already answers for, so it has to reach the user the same way.
    reply = _run("$mju 11055927171882 2x")

    assert reply is not None, "the command died before it could reply"
    assert reply.type is ReplyType.ERROR
    assert "图片序号" in reply.content
    assert "2x" in reply.content


def test_numeric_index_still_replies_with_the_range_message():
    # Catching the parse failure must not swallow the existing 1..4 guard.
    reply = _run("$mju 11055927171882 9")

    assert reply.type is ReplyType.ERROR
    assert "应在 1 至 4 之间" in reply.content
