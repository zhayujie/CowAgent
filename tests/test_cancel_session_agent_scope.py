# encoding:utf-8
"""produce() files a session's queue under an agent-scoped key.

``ChatChannel.produce`` keys ``self.sessions`` with the agent-scoped session key
("keep legacy token keys for the default agent, namespace the rest"), while the
cancel paths looked the bare session id up, so for any Agent other than the
default one they found no queue at all. The two callers that cancel queued work
-- ``#reset`` and the Feishu recall handler -- pass the Agent produce() routed
to, which is what makes the lookup land.
"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import config
from bridge.agent_bridge import AgentBridge
from bridge.context import Context, ContextType
from channel.chat_channel import ChatChannel
from common import const
from common.dequeue import Dequeue
from plugins import Event, EventContext

SESSION_ID = "web:u1"


class _StubAgentBridge:
    """Routes every context to one Agent, with AgentBridge's own key rules."""

    def __init__(self, routed: str, default: str = "default"):
        self.routed = routed
        self.agent_registry = SimpleNamespace(
            default_agent_id=default,
            get=lambda agent_id=None: SimpleNamespace(id=agent_id or default),
        )

    def route_context(self, context):
        context["agent_id"] = self.routed
        return self.routed

    _resolve_agent_id = AgentBridge._resolve_agent_id
    _cancel_key = staticmethod(AgentBridge._cancel_key)
    scoped_session_key = AgentBridge.scoped_session_key


def _patch_bridge(monkeypatch, stub):
    monkeypatch.setattr(
        "bridge.bridge.Bridge", lambda: SimpleNamespace(get_agent_bridge=lambda: stub)
    )
    monkeypatch.setattr("channel.chat_channel.conf", lambda: {"concurrency_in_session": 1})


def _bare_channel(*keys):
    """A channel whose sessions dict holds one queued message per key."""
    channel = ChatChannel.__new__(ChatChannel)
    channel.lock = threading.RLock()
    channel.futures = {}
    channel.sessions = {}
    for key in keys:
        queue = Dequeue()
        queue.put(Context(ContextType.TEXT, "queued", {"session_id": SESSION_ID}))
        channel.sessions[key] = [queue, MagicMock()]
    return channel


def test_produce_queues_a_non_default_agent_under_a_scoped_key(monkeypatch):
    _patch_bridge(monkeypatch, _StubAgentBridge("team-a"))
    channel = _bare_channel()
    context = Context(ContextType.TEXT, "hello", {"session_id": SESSION_ID})

    ChatChannel.produce(channel, context)

    assert list(channel.sessions) == ["team-a::" + SESSION_ID]


def test_cancel_session_drains_the_scoped_queue_produce_created(monkeypatch):
    _patch_bridge(monkeypatch, _StubAgentBridge("team-a"))
    channel = _bare_channel("team-a::" + SESSION_ID)

    channel.cancel_session(SESSION_ID, agent_id="team-a")

    assert channel.sessions["team-a::" + SESSION_ID][0].qsize() == 0


def test_cancel_session_still_cancels_futures_recorded_under_the_scoped_key(monkeypatch):
    _patch_bridge(monkeypatch, _StubAgentBridge("team-a"))
    channel = _bare_channel("team-a::" + SESSION_ID)
    # consume() records futures under the key it pulled from self.sessions.
    future = MagicMock()
    channel.futures["team-a::" + SESSION_ID] = [future]

    channel.cancel_session(SESSION_ID, agent_id="team-a")

    future.cancel.assert_called_once()


@pytest.mark.parametrize("cancel_agent_id", [None, "default"])
def test_default_agent_keeps_using_the_bare_session_key(monkeypatch, cancel_agent_id):
    """The un-namespaced legacy key keeps working, with or without the new argument."""
    _patch_bridge(monkeypatch, _StubAgentBridge("default"))
    channel = _bare_channel(SESSION_ID)

    channel.cancel_session(SESSION_ID, agent_id=cancel_agent_id)

    assert channel.sessions[SESSION_ID][0].qsize() == 0


def test_cancel_message_removes_the_recalled_context_from_the_scoped_queue(monkeypatch):
    _patch_bridge(monkeypatch, _StubAgentBridge("team-a"))
    registry = MagicMock()
    registry.cancel_request.return_value = False
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)
    channel = _bare_channel()
    queue = Dequeue()
    for message_id in ("m1", "m2", "m3"):
        context = Context(ContextType.TEXT, message_id, {"session_id": SESSION_ID})
        context["msg"] = SimpleNamespace(msg_id=message_id)
        queue.put(context)
    channel.sessions["team-a::" + SESSION_ID] = [queue, MagicMock()]

    removed, active = channel.cancel_message(SESSION_ID, "m2", agent_id="team-a")

    assert (removed, active) == (1, False)
    remaining = channel.sessions["team-a::" + SESSION_ID][0]
    assert [remaining.get_nowait().get("msg").msg_id for _ in range(2)] == ["m1", "m3"]


class _ChatBridge:
    """Stands in for the bot bridge the command parser reads before dispatching."""

    chat_bots = {}

    def __init__(self, *args, **kwargs):
        pass

    def get_bot_type(self, bot_role):
        return const.OPENAI

    def get_bot(self, bot_role):
        return SimpleNamespace(sessions=MagicMock())


def _run_godcmd(content, tmp_path, monkeypatch, agent_id):
    """Hand ``content`` to the command parser and return the channel it used.

    The plugin is built against a config under ``tmp_path`` (``__file__`` is what
    the module uses for its own directory, ``Plugin.path`` what ``load_config``
    reads), so neither points at the repository's own config.json.
    """
    import plugins

    # ``@plugins.register`` reads the importing plugin's path off the plugin
    # instance, so it has to be pointed at the godcmd directory before the import.
    plugins.instance.current_plugin_path = "./plugins/godcmd"
    import plugins.godcmd.godcmd as godcmd_module

    plugins.instance.current_plugin_path = None
    Godcmd = plugins.instance.plugins["GODCMD"]

    monkeypatch.setattr(godcmd_module, "__file__", str(tmp_path / "godcmd.py"))
    monkeypatch.setattr(Godcmd, "path", str(tmp_path))
    (tmp_path / "config.json").write_text(
        '{"password": "secret", "admin_users": ["u1"]}', encoding="utf-8"
    )
    config.plugin_config.pop("godcmd", None)
    channel = MagicMock()
    try:
        with patch.object(godcmd_module, "conf", lambda: {"model": "gpt-4o", "clear_memory_commands": []}), \
                patch.object(godcmd_module, "Bridge", _ChatBridge):
            context = Context(ContextType.TEXT, content)
            context["session_id"] = SESSION_ID
            context["receiver"] = "u1"
            if agent_id is not None:
                # produce() resolved the route before queueing this command.
                context["agent_id"] = agent_id
            event = EventContext(
                Event.ON_HANDLE_CONTEXT,
                {"context": context, "reply": None, "channel": channel},
            )
            Godcmd().on_handle_context(event)
        return channel
    finally:
        config.plugin_config.pop("godcmd", None)


def test_reset_cancels_the_queue_of_the_agent_it_ran_on(tmp_path, monkeypatch):
    channel = _run_godcmd("#reset", tmp_path, monkeypatch, "team-a")

    channel.cancel_session.assert_called_once_with(SESSION_ID, agent_id="team-a")


def test_reset_keeps_working_for_the_default_agent(tmp_path, monkeypatch):
    channel = _run_godcmd("#reset", tmp_path, monkeypatch, None)

    channel.cancel_session.assert_called_once_with(SESSION_ID, agent_id=None)
