# encoding:utf-8
"""Channel users: the people who wrote in over an IM channel.

The console's own conversations are the ``web`` channel. Everyone who reached
the Agent through WeChat, Feishu, Telegram and so on is in the same store under
their own channel type, and until now nothing in the console could show them --
the sessions list asked for ``channel_type="web"``. Two ways that goes wrong
quietly: a channel user leaks into the console's own session list, or the new
list shows the console's sessions as if they were contacts.

The store side and the endpoint side are both pinned here. ``/api/history`` is
reused unchanged to read a transcript, so what this endpoint has to get right is
who exists, which channel and Agent each belongs to, and that the page is a
merge across Agents rather than one Agent's database.
"""

import json
import os
import sys
import types
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub

from channel.web.api import sessions as sessions_api

ChannelSessionsHandler = sessions_api.ChannelSessionsHandler


def _store(tmp_path, agent_id=""):
    from agent.memory.conversation_store import ConversationStore

    return ConversationStore(tmp_path / "index.db", agent_id=agent_id)


def _session(store, session_id, channel_type, text="hi", when=None):
    store.append_messages(
        session_id=session_id,
        channel_type=channel_type,
        messages=[
            {"role": "user", "content": text},
            {"role": "assistant", "content": "ok"},
        ],
    )
    if when is not None:
        # last_active is what the list sorts on, and two sessions written in the
        # same second would otherwise tie.
        import sqlite3

        conn = sqlite3.connect(str(store._db_path))
        try:
            with conn:
                conn.execute(
                    "UPDATE sessions SET last_active = ? WHERE session_id = ?",
                    (when, session_id),
                )
        finally:
            conn.close()


# ---------------------------------------------------------------- the store


def test_the_console_s_own_sessions_are_not_channel_users(tmp_path):
    store = _store(tmp_path)
    _session(store, "session_web", "web")
    _session(store, "wx_user", "weixin")

    result = store.list_channel_sessions()

    assert [s["session_id"] for s in result["sessions"]] == ["wx_user"]
    assert result["total"] == 1


def test_every_row_says_which_channel_it_came_from(tmp_path):
    """One list spans several channels, so a row that did not say which one it
    came from could not be labelled."""
    store = _store(tmp_path)
    _session(store, "wx_user", "weixin")
    _session(store, "fs_user", "feishu", when=2_000_000_000)

    result = store.list_channel_sessions()

    assert [s["channel_type"] for s in result["sessions"]] == ["feishu", "weixin"]
    assert [s["session_id"] for s in result["sessions"]] == ["fs_user", "wx_user"]


def test_one_channel_can_be_asked_for_on_its_own(tmp_path):
    store = _store(tmp_path)
    _session(store, "wx_user", "weixin")
    _session(store, "fs_user", "feishu")

    result = store.list_channel_sessions(channel_type="weixin")

    assert [s["session_id"] for s in result["sessions"]] == ["wx_user"]
    assert result["total"] == 1


def test_a_row_with_no_channel_type_is_not_invented_as_a_contact(tmp_path):
    """Sessions written before the channel type was recorded have an empty one.
    They are not the console's, but nothing says they are a channel user's
    either, so showing them would invent contacts."""
    store = _store(tmp_path)
    _session(store, "anonymous", "")

    assert store.list_channel_sessions()["sessions"] == []


def test_the_filter_offers_only_channels_that_have_someone_behind_them(tmp_path):
    store = _store(tmp_path)
    _session(store, "wx_user", "weixin", when=1_000)
    _session(store, "wx_user2", "weixin", when=2_000)
    _session(store, "fs_user", "feishu", when=3_000)
    _session(store, "session_web", "web", when=4_000)

    channels = store.list_channel_types()

    assert channels == [
        {"channel_type": "feishu", "session_count": 1, "last_active": 3_000},
        {"channel_type": "weixin", "session_count": 2, "last_active": 2_000},
    ]


def test_channels_are_counted_per_agent(tmp_path):
    """One database per Agent, so a count that ignored the agent would report
    another Agent's contacts as this one's."""
    first = _store(tmp_path / "a", agent_id="alpha")
    second = _store(tmp_path / "b", agent_id="beta")
    _session(first, "wx_a", "weixin", when=1_000)
    _session(second, "wx_b", "weixin", when=2_000)
    _session(second, "wx_c", "weixin", when=3_000)

    assert first.list_channel_types() == [
        {"channel_type": "weixin", "session_count": 1, "last_active": 1_000}
    ]
    assert second.list_channel_types() == [
        {"channel_type": "weixin", "session_count": 2, "last_active": 3_000}
    ]


# ---------------------------------------------------------------- the endpoint


@pytest.fixture
def two_agents(tmp_path):
    """A default and a second Agent, each with its own channel conversation."""
    from agent.memory import (
        clear_conversation_store_cache,
        get_conversation_store,
        reset_memory_configs,
    )
    from agent.registry import AgentProfile, AgentRegistry, set_agent_registry

    primary_dir = tmp_path / "primary"
    writer_dir = tmp_path / "writer"
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(primary_dir)),
            AgentProfile("writer", "Writer", str(writer_dir)),
        ],
        default_agent_id="primary",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    reset_memory_configs()

    primary = get_conversation_store(str(primary_dir))
    writer = get_conversation_store(str(writer_dir))
    _session(primary, "wx_primary", "weixin", text="第一个用户", when=1_000)
    _session(primary, "session_web", "web", when=5_000)
    _session(writer, "fs_writer", "feishu", text="second user", when=2_000)

    try:
        yield {"primary": primary, "writer": writer}
    finally:
        reset_memory_configs()
        clear_conversation_store_cache()
        set_agent_registry(None)


class _FakeRecipientStore:
    def __init__(self, entries):
        self._entries = entries

    def list(self):
        return list(self._entries)


def _get(handler=ChannelSessionsHandler, contacts=None, **params):
    query = {"channel_type": "", "page": "1", "page_size": "50", "agent_id": ""}
    query.update(params)
    fake = _FakeRecipientStore(contacts or [])
    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api.web, "input",
                      return_value=types.SimpleNamespace(**query)), \
         patch.object(sessions_api.web, "header"), \
         patch("agent.tools.scheduler.integration.get_recipient_store",
               return_value=fake):
        return json.loads(handler().GET())


def test_the_list_merges_agents_and_says_which_agent_each_user_talks_to(two_agents):
    """A channel instance binds to one Agent. Showing only the console's
    current Agent would hide users whose channel is bound elsewhere and read as
    "nobody has written in"."""
    data = _get()

    assert data["status"] == "success"
    assert [s["session_id"] for s in data["sessions"]] == ["fs_writer", "wx_primary"]
    assert [s["agent_id"] for s in data["sessions"]] == ["writer", "primary"]
    assert [s["agent"]["name"] for s in data["sessions"]] == ["Writer", "Primary"]
    assert data["total"] == 2


def test_the_console_s_own_conversations_stay_out_of_the_list(two_agents):
    data = _get()

    assert "session_web" not in [s["session_id"] for s in data["sessions"]]


def test_an_agent_filter_narrows_the_list(two_agents):
    data = _get(agent_id="writer")

    assert [s["session_id"] for s in data["sessions"]] == ["fs_writer"]
    assert data["total"] == 1


def test_the_channel_filter_is_honoured(two_agents):
    data = _get(channel_type="weixin")

    assert [s["session_id"] for s in data["sessions"]] == ["wx_primary"]
    assert data["total"] == 1


def test_the_filter_chips_count_every_channel_even_while_one_is_selected(two_agents):
    """The chips are how the user gets back to the other channels, so selecting
    one must not shrink the rest to nothing."""
    data = _get(channel_type="weixin")

    assert {c["channel_type"]: c["session_count"] for c in data["channels"]} == {
        "weixin": 1,
        "feishu": 1,
    }


def test_a_contact_name_from_the_directory_is_shown_instead_of_the_id(two_agents):
    """A WeChat id is not a name. The recipient directory already records one
    for scheduled delivery, so the list reads it rather than showing the id."""
    data = _get(contacts=[{
        "channel_type": "weixin",
        "instance_id": "weixin",
        "receiver": "wx_primary",
        "name": "小王",
        "is_group": False,
        "session_id": "wx_primary",
    }])

    by_id = {s["session_id"]: s for s in data["sessions"]}
    assert by_id["wx_primary"]["name"] == "小王"
    # No name learned for this one, so the id stands in rather than an empty row.
    assert by_id["fs_writer"]["name"] == "fs_writer"


def test_a_name_that_is_only_the_id_again_is_not_treated_as_a_name(two_agents):
    """The directory falls back to the receiver id when the channel never
    learned a name; showing that as the display name adds nothing."""
    data = _get(contacts=[{
        "channel_type": "feishu",
        "instance_id": "feishu",
        "receiver": "fs_writer",
        "name": "fs_writer",
        "is_group": False,
        "session_id": "fs_writer",
    }])

    by_id = {s["session_id"]: s for s in data["sessions"]}
    assert by_id["fs_writer"]["name"] == "fs_writer"
    assert by_id["fs_writer"]["is_group"] is False


def test_an_unreadable_contact_directory_still_returns_the_list(two_agents):
    """Names are decoration. Losing them must not cost the user the list."""
    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api.web, "input",
                      return_value=types.SimpleNamespace(
                          channel_type="", page="1", page_size="50", agent_id="")), \
         patch.object(sessions_api.web, "header"), \
         patch("agent.tools.scheduler.integration.get_recipient_store",
               side_effect=RuntimeError("no directory")):
        data = json.loads(ChannelSessionsHandler().GET())

    assert data["status"] == "success"
    assert len(data["sessions"]) == 2


def test_one_unreadable_agent_does_not_blank_out_the_others(two_agents):
    """Sessions live one database per Agent, so a merge has to survive one of
    them failing instead of returning nothing."""
    from agent.memory import get_conversation_store

    real = get_conversation_store

    def half_broken(workspace, *args, **kwargs):
        if "writer" in str(workspace):
            raise RuntimeError("unreadable workspace")
        return real(workspace, *args, **kwargs)

    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api.web, "input",
                      return_value=types.SimpleNamespace(
                          channel_type="", page="1", page_size="50", agent_id="")), \
         patch.object(sessions_api.web, "header"), \
         patch("agent.memory.get_conversation_store", side_effect=half_broken), \
         patch("agent.tools.scheduler.integration.get_recipient_store",
               return_value=_FakeRecipientStore([])):
        data = json.loads(ChannelSessionsHandler().GET())

    assert [s["session_id"] for s in data["sessions"]] == ["wx_primary"]


def test_only_the_contacts_on_this_page_are_looked_up(two_agents):
    """The directory holds every contact of every channel; a page asks it only
    about the people the page is about to draw."""
    seen = {}
    real = sessions_api._channel_contacts

    def spy(wanted=None):
        seen["wanted"] = wanted
        return real(wanted)

    with patch.object(sessions_api, "_channel_contacts", side_effect=spy):
        data = _get(page_size="1")

    assert data["sessions"], "the page has to have a row to ask about"
    assert seen["wanted"] == {s["session_id"] for s in data["sessions"]}


def test_a_page_past_the_merge_cap_stops_offering_more(two_agents, monkeypatch):
    """The row take offered to each Agent grows with the page number and comes
    from a query parameter. Past the cap the list says so instead of promising a
    page it will not build."""
    monkeypatch.setattr(sessions_api, "MAX_MERGE_ROWS", 2)

    data = _get(page="2", page_size="50")

    assert data["status"] == "success"
    assert data["has_more"] is False
