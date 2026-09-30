# encoding:utf-8
"""``#model`` with more than one argument must answer, not leak a placeholder.

``Godcmd.on_handle_context`` initialises the reply text with the sentinel
``result = "string"`` (plugins/godcmd/godcmd.py:262) and every command branch is
expected to overwrite it. ``model`` handles no arguments (line 286, "current
model") and exactly one (line 289, set it), and nothing else -- so
``#model gpt-4o now`` matches no branch, leaves the sentinel in place and sends
the word ``string`` to the user as the reply body.

The two commands that take one argument from the user answer a wrong count
instead: ``set_openai_api_key`` replies "请提供一个api_key" (line 305) and
``set_gpt_model`` replies "请提供一个GPT模型" (line 319). The reply is built from
``result`` either way (lines 449-453), so only this one branch can ship its
internal placeholder.
"""

from unittest.mock import patch

import config
import plugins
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from common import const
from plugins import Event, EventContext

# ``@plugins.register`` reads the importing plugin's path off the plugin
# instance, so it has to be pointed at the godcmd directory before the import.
plugins.instance.current_plugin_path = "./plugins/godcmd"
import plugins.godcmd.godcmd as godcmd_module  # noqa: E402

plugins.instance.current_plugin_path = None

# The decorator hands the class to the plugin manager and binds nothing back,
# so the module attribute is None and the registered class has to be taken from
# the manager the same way the runtime does.
Godcmd = plugins.instance.plugins["GODCMD"]

ADMIN = "u1"
CURRENT = "gpt-4o"


class FakeBridge:
    """Stands in for the bot bridge, which the command parser reads first."""

    def __init__(self, *args, **kwargs):
        pass

    def get_bot_type(self, bot_role):
        return const.OPENAI

    def get_bot(self, bot_role):
        return None

    def reset_bot(self):
        pass


def _run(content, tmp_path, monkeypatch):
    """Hand ``content`` to the command parser and report what came back.

    The plugin is built against a config under ``tmp_path``: ``__file__`` is
    what the module uses for its own directory and ``Plugin.path`` is what
    ``load_config`` reads, so both are redirected rather than pointed at the
    repository's own config.json. ``conf()`` is stubbed so the model branch
    reads a known global model instead of whatever the developer has set.
    """
    monkeypatch.setattr(godcmd_module, "__file__", str(tmp_path / "godcmd.py"))
    monkeypatch.setattr(Godcmd, "path", str(tmp_path))
    (tmp_path / "config.json").write_text(
        '{"password": "secret", "admin_users": ["%s"]}' % ADMIN, encoding="utf-8"
    )
    config.plugin_config.pop("godcmd", None)
    conf_values = {"model": CURRENT, "clear_memory_commands": []}
    try:
        with patch.object(godcmd_module, "conf", lambda: conf_values), patch.object(
            godcmd_module, "Bridge", FakeBridge
        ):
            plugin = Godcmd()
            context = Context(ContextType.TEXT, content)
            context["session_id"] = "s1"
            context["receiver"] = ADMIN
            event = EventContext(
                Event.ON_HANDLE_CONTEXT,
                {"context": context, "reply": None, "channel": object()},
            )
            plugin.on_handle_context(event)
        return event["reply"], conf_values
    finally:
        config.plugin_config.pop("godcmd", None)


def test_extra_argument_gets_a_reply_that_is_not_the_placeholder(tmp_path, monkeypatch):
    reply, _ = _run("#model %s now" % CURRENT, tmp_path, monkeypatch)

    assert reply is not None
    assert reply.type is ReplyType.ERROR
    # The sentinel the command used to answer with: an internal placeholder
    # string, which tells the user nothing about what they typed wrong.
    assert reply.content != "string"
    assert "模型" in reply.content


def test_no_argument_still_reports_the_current_model(tmp_path, monkeypatch):
    # The guard must not swallow the documented read path.
    reply, _ = _run("#model", tmp_path, monkeypatch)

    assert reply.type is ReplyType.INFO
    assert CURRENT in reply.content


def test_one_unknown_name_still_reports_it(tmp_path, monkeypatch):
    reply, _ = _run("#model nosuchmodel", tmp_path, monkeypatch)

    assert reply.type is ReplyType.ERROR
    assert "模型名称不存在" in reply.content
