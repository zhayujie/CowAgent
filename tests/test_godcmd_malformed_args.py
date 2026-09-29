# encoding:utf-8
"""godcmd answers a command whose arguments it cannot use.

Two admin-side commands did not:

* ``#model a b`` matched neither the no-argument nor the one-argument branch,
  so the reply carried the ``"string"`` placeholder ``result`` starts out as.
* ``#setpri NAME abc`` passed ``int("abc")`` straight through; the ValueError
  escaped ``on_handle_context`` and the admin got no reply at all.
"""
import importlib

import pytest

import config
import plugins
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from plugins.event import Event, EventAction, EventContext

ADMIN = "admin-user"


class _Bridge:
    def get_bot_type(self, _):
        return "stub"

    def get_bot(self, _):
        return None


class _PluginManager:
    def __init__(self):
        self.priorities = []

    def set_plugin_priority(self, name, priority):
        self.priorities.append((name, priority))
        return True


@pytest.fixture
def godcmd(tmp_path, monkeypatch):
    config.plugin_config.pop("godcmd", None)
    plugins.instance.current_plugin_path = "./plugins/godcmd"
    try:
        module = importlib.import_module("plugins.godcmd.godcmd")
    finally:
        plugins.instance.current_plugin_path = None
    cls = plugins.instance.plugins["GODCMD"]
    monkeypatch.setattr(module, "__file__", str(tmp_path / "godcmd.py"))
    monkeypatch.setattr(cls, "path", str(tmp_path))
    (tmp_path / "config.json").write_text(
        '{"password": "pw", "admin_users": ["%s"]}' % ADMIN, encoding="utf-8"
    )
    monkeypatch.setattr(module, "Bridge", _Bridge)
    manager = _PluginManager()
    monkeypatch.setattr(module, "PluginManager", lambda: manager)
    yield cls(), manager
    config.plugin_config.pop("godcmd", None)


def _run(plugin, content):
    context = Context(ContextType.TEXT, content)
    context["receiver"] = ADMIN
    context["session_id"] = ADMIN
    context["isgroup"] = False
    e_context = EventContext(
        Event.ON_HANDLE_CONTEXT, {"channel": None, "context": context, "reply": None}
    )
    plugin.on_handle_context(e_context)
    assert e_context.action == EventAction.BREAK_PASS
    return e_context["reply"]


def test_model_with_too_many_arguments_is_answered(godcmd):
    plugin, _ = godcmd

    reply = _run(plugin, "#model gpt-4o extra")

    assert reply.type == ReplyType.ERROR
    assert reply.content != "string"


def test_setpri_with_a_non_integer_priority_is_answered(godcmd):
    plugin, manager = godcmd

    reply = _run(plugin, "#setpri Banwords abc")

    assert reply.type == ReplyType.ERROR
    assert manager.priorities == []


def test_setpri_with_an_integer_priority_still_works(godcmd):
    plugin, manager = godcmd

    reply = _run(plugin, "#setpri Banwords 5")

    assert reply.type == ReplyType.INFO
    assert manager.priorities == [("Banwords", 5)]
