# encoding:utf-8
"""``#setpri`` with a priority that is not a number must answer, not die.

``Godcmd.on_handle_context`` guards the *count* of the arguments and then reads
the second one with a bare ``int(args[1])`` (plugins/godcmd/godcmd.py:397). The
other way to get that command wrong -- one argument, or three -- is answered
with the usage text (line 395), and every sibling admin command answers a wrong
argument the same way (``reloadp`` line 404, ``enablep`` line 413, ``installp``
line 427), but a priority of ``high`` instead of ``3`` raises ``ValueError``
out of ``on_handle_context``. Nothing on the way back catches it:
``PluginManager.emit_event`` calls the handler directly
(plugins/plugin_manager.py:287-297), ``ChatChannel._handle`` has no try/except
around it (channel/chat_channel.py:191-209) and the worker's callback only logs
(channel/chat_channel.py:452-453). So an admin typing ``#setpri keyword high``
gets no reply at all, and the plugin -- which ships enabled and is the one that
answers ``#help`` -- looks frozen to them.
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


class FakeBridge:
    """Stands in for the bot bridge, which the command parser reads first."""

    def __init__(self, *args, **kwargs):
        pass

    def get_bot_type(self, bot_role):
        return const.OPENAI

    def get_bot(self, bot_role):
        return None


class FakePluginManager:
    """Records what the command asks for instead of rewriting plugins.json."""

    def __init__(self, calls):
        self.calls = calls

    def set_plugin_priority(self, name, priority):
        self.calls.append((name, priority))
        return name.upper() == "KEYWORD"


def _run(content, tmp_path, monkeypatch):
    """Hand ``content`` to the admin command parser and report what came back.

    The plugin is built against a config under ``tmp_path``: ``__file__`` is
    what the module uses for its own directory and ``Plugin.path`` is what
    ``load_config`` reads, so both are redirected rather than pointed at the
    repository's own config.json. ``Plugin.load_config`` caches into
    ``config.plugin_config``, so that entry is dropped before and after.
    """
    monkeypatch.setattr(
        godcmd_module, "__file__", str(tmp_path / "godcmd.py")
    )
    monkeypatch.setattr(Godcmd, "path", str(tmp_path))
    (tmp_path / "config.json").write_text(
        '{"password": "secret", "admin_users": ["%s"]}' % ADMIN, encoding="utf-8"
    )
    config.plugin_config.pop("godcmd", None)
    calls = []
    try:
        plugin = Godcmd()
        context = Context(ContextType.TEXT, content)
        context["session_id"] = "s1"
        context["receiver"] = ADMIN
        event = EventContext(
            Event.ON_HANDLE_CONTEXT,
            {"context": context, "reply": None, "channel": object()},
        )
        with patch.object(godcmd_module, "Bridge", FakeBridge), patch.object(
            godcmd_module, "PluginManager", lambda: FakePluginManager(calls)
        ):
            plugin.on_handle_context(event)
        return event["reply"], calls
    finally:
        config.plugin_config.pop("godcmd", None)


def test_non_numeric_priority_gets_a_reply_instead_of_raising(tmp_path, monkeypatch):
    # Typing the priority as a word is the same class of user mistake as the
    # wrong argument count the command already answers for, so it has to reach
    # the user the same way.
    reply, calls = _run("#setpri keyword high", tmp_path, monkeypatch)

    assert reply is not None, "the command died before it could reply"
    assert reply.type is ReplyType.ERROR
    assert "优先级" in reply.content
    assert "high" in reply.content
    # The unparsable value must not be handed to the manager as a number.
    assert calls == []


def test_numeric_priority_still_reaches_the_plugin_manager(tmp_path, monkeypatch):
    # Rejecting the unparsable value must not swallow the documented command.
    reply, calls = _run("#setpri keyword 7", tmp_path, monkeypatch)

    assert calls == [("keyword", 7)]
    assert reply.type is ReplyType.INFO
    assert "优先级已设置为7" in reply.content


def test_unknown_plugin_with_a_numeric_priority_still_reports_it(tmp_path, monkeypatch):
    # The manager's own answer for an unknown plugin has to survive the guard.
    reply, calls = _run("#setpri nosuch 3", tmp_path, monkeypatch)

    assert calls == [("nosuch", 3)]
    assert reply.type is ReplyType.ERROR
    assert "插件不存在" in reply.content
