"""Untrusted page windows are clamped before they reach SQLite."""

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
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(
        wsgifunc=lambda: None
    )
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *a, **k: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *a, **k: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub


SESSION_COUNT = 5


@pytest.fixture
def store(tmp_path):
    """A real store holding SESSION_COUNT two-turn web sessions."""
    from agent.memory.conversation_store import ConversationStore

    instance = ConversationStore(tmp_path / "history.db")
    for index in range(SESSION_COUNT):
        instance.append_messages(
            session_id=f"s{index}",
            channel_type="web",
            messages=[
                {"role": "user", "content": f"q{index}"},
                {"role": "assistant", "content": f"a{index}"},
            ],
        )
    return instance


@pytest.mark.parametrize("bad_size", [-1, 0, -(10 ** 9)])
def test_a_non_positive_page_size_reads_one_row_per_page(store, bad_size):
    result = store.list_sessions(channel_type="web", page=1, page_size=bad_size)
    assert result["page_size"] == 1 and len(result["sessions"]) == 1


def test_junk_values_fall_back_to_defaults(store):
    result = store.list_sessions(channel_type="web", page="x", page_size="abc")
    assert (result["page"], result["page_size"]) == (1, 50)


def test_the_store_listing_is_not_capped_for_the_cross_agent_merge(store):
    result = store.list_sessions(channel_type="web", page=1, page_size=1000)
    assert result["page_size"] == 1000 and len(result["sessions"]) == SESSION_COUNT


def test_history_page_size_is_capped_and_zero_is_safe(store):
    from agent.memory.conversation_store import MAX_PAGE_SIZE

    assert store.load_history_page(session_id="s0", page=1, page_size=10 ** 9)["page_size"] == MAX_PAGE_SIZE
    result = store.load_history_page(session_id="s0", page=1, page_size=0, until_seq=1)
    assert result["page_size"] == 1 and result["messages"]


@pytest.mark.parametrize("raw, expected", [
    (("1", "10"), (1, 10)),
    (("0", "-5"), (1, 1)),
    (("-3", str(10 ** 9)), (1, 200)),
    ((None, None), (1, 50)),
])
def test_page_window(raw, expected):
    from agent.memory.conversation_store import page_window

    assert page_window(*raw, 50) == expected


def test_dispatch_caps_a_remote_page_size(monkeypatch):
    from agent.chat.session_service import SessionService

    seen = {}
    monkeypatch.setattr(SessionService, "list_sessions", lambda self, **kw: seen.update(kw) or {})
    SessionService().dispatch("list_sessions", {"page": "0", "page_size": "100000"})
    assert (seen["page"], seen["page_size"]) == (1, 200)


def test_the_sessions_endpoint_clamps_before_merging_agents(store, tmp_path):
    # scope=all multiplies page * page_size and slices the merged list itself,
    # so the handler has to clamp before that arithmetic, not just at the store.
    from channel.web.api import sessions as sessions_api

    params = types.SimpleNamespace(
        page="1", page_size="-1", agent_id="", agent="", scope="all", space=""
    )

    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api.web, "header", lambda *a, **k: None), \
         patch.object(sessions_api.web, "input", lambda **kwargs: params), \
         patch("agent.memory.get_conversation_store", lambda *a, **k: store), \
         patch("agent.registry.get_agent_registry") as registry:
        registry.return_value.list.return_value = []
        response = json.loads(sessions_api.SessionsHandler().GET())

    assert response["status"] == "success"
    assert response["page_size"] >= 1
    assert len(response["sessions"]) < SESSION_COUNT


def test_the_history_endpoint_survives_a_zero_page_size(store):
    from channel.web.api import sessions as sessions_api

    params = types.SimpleNamespace(
        session_id="s0", page="1", page_size="0", agent_id="", until_seq="1"
    )

    class _NoLiveStream:
        def resumable_stream(self, session_id, agent_id=None):
            return None

    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api.web, "header", lambda *a, **k: None), \
         patch.object(sessions_api.web, "input", lambda **kwargs: params), \
         patch.object(sessions_api, "WebChannel", _NoLiveStream), \
         patch("agent.memory.get_conversation_store", lambda *a, **k: store), \
         patch("agent.workspace.project_store.get_project_dir", return_value=None):
        response = json.loads(sessions_api.HistoryHandler().GET())

    assert response["status"] == "success"
    assert response["messages"]
