"""The session list reports every project space and can page one space alone."""

import json
import os
import sys
import types
from contextlib import contextmanager
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
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(
        wsgifunc=lambda: None
    )
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *a, **k: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *a, **k: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub

DEFAULT = "__default__"
PROJECTS = {"s0": "/work/alpha", "s1": "/work/alpha", "s2": "/work/beta"}


@pytest.fixture
def store(tmp_path):
    """Six web sessions: two in alpha, one in beta, three in the default space."""
    from agent.memory.conversation_store import ConversationStore

    instance = ConversationStore(tmp_path / "history.db")
    for index in range(6):
        instance.append_messages(
            session_id=f"s{index}",
            channel_type="web",
            messages=[
                {"role": "user", "content": f"q{index}"},
                {"role": "assistant", "content": f"a{index}"},
            ],
        )
    return instance


@contextmanager
def _endpoint(store, **query):
    from channel.web.api import sessions as sessions_api

    params = types.SimpleNamespace(
        page="1", page_size="50", agent_id="", agent="", scope="all", space=""
    )
    for key, value in query.items():
        setattr(params, key, value)
    profile = types.SimpleNamespace(id="", workspace="unused")
    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api, "_agent_badge", lambda p: None), \
         patch.object(sessions_api.web, "header", lambda *a, **k: None), \
         patch.object(sessions_api.web, "input", lambda **kwargs: params), \
         patch("agent.memory.get_conversation_store", lambda *a, **k: store), \
         patch("agent.workspace.project_store.get_project_map", lambda *a, **k: PROJECTS), \
         patch("agent.workspace.project_store.display_name_for", os.path.basename), \
         patch("agent.workspace.project_store.get_order", lambda: []), \
         patch("agent.workspace.session_prefs.members_index", lambda: {}), \
         patch("agent.registry.get_agent_registry") as registry:
        registry.return_value.list.return_value = [profile]
        yield lambda: json.loads(sessions_api.SessionsHandler().GET())


def test_every_space_is_reported_with_its_true_count(store):
    with _endpoint(store, page_size="2") as get:
        response = get()

    counts = {space["key"]: space["count"] for space in response["spaces"]}
    assert counts == {"/work/alpha": 2, "/work/beta": 1, DEFAULT: 3}
    assert response["group_mode"] == "project" and response["space_count"] == 3
    assert len(response["sessions"]) == 2
    names = {space["key"]: space["name"] for space in response["spaces"]}
    assert names["/work/alpha"] == "alpha" and names[DEFAULT] == ""


def test_one_space_pages_on_its_own(store):
    with _endpoint(store, space="/work/alpha") as get:
        response = get()

    assert sorted(s["session_id"] for s in response["sessions"]) == ["s0", "s1"]
    assert response["total"] == 2 and response["has_more"] is False
    assert len(response["spaces"]) == 3


def test_the_default_space_pages_by_its_sentinel(store):
    with _endpoint(store, space=DEFAULT, page_size="2") as get:
        first = get()
    with _endpoint(store, space=DEFAULT, page="2", page_size="2") as get:
        second = get()

    ids = [s["session_id"] for s in first["sessions"] + second["sessions"]]
    assert sorted(ids) == ["s3", "s4", "s5"]
    assert first["total"] == 3 and first["has_more"] is True and second["has_more"] is False
    assert all(s["project"] is None for s in first["sessions"])


def test_births_list_every_session_of_the_channel(store):
    births = dict(store.list_session_births(channel_type="web"))
    assert sorted(births) == [f"s{i}" for i in range(6)]
    assert all(births.values())
