# encoding:utf-8
"""Guest pages answered for a front end on the control connection.

The front end authenticates visitors itself and names the profile, visitor and
conversation; everything after that must hold exactly as for the /share pages:
the confined runtime answers, widenings on disk wait for a confirm, a visitor
only reaches their own conversations and files, and no real path leaves.
None of it depends on the instance serving /share pages itself.
"""

import json
import shutil
import threading

import pytest

import config
from agent.guest import store
from agent.guest.profile import guests_root, load_profile
from agent.guest.actions import dispatch
from tests.test_guest_share import _ScriptedModel

ALL_TOOLS = ["read", "ls", "search_files", "write", "edit", "send", "web_search", "web_fetch", "vision", "time"]


@pytest.fixture
def guest_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("COW_DATA_DIR", str(data))
    # The instance's own /share pages stay off.
    monkeypatch.setitem(config.conf(), "guest_share", {"enabled": False})
    monkeypatch.setitem(config.conf(), "web_password", "")
    from agent.guest import runtime

    monkeypatch.setattr(runtime, "_service", None)
    root = guests_root()
    try:
        yield tmp_path
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _ok(action, payload, send_chunk=None):
    result = dispatch(action, payload, send_chunk)
    assert result["code"] == 200, result
    return result["payload"]


def _refused(action, payload):
    result = dispatch(action, payload)
    assert result["code"] != 200, result
    return result["code"], (result["payload"] or {}).get("reason")


def _upsert(slug="web-demo", **config):
    body = {"name": "Demo", "tools": ALL_TOOLS}
    body.update(config)
    return _ok("upsert", {"slug": slug, "config": body, "guest_md": "Answer product questions."})


def _visitor():
    visitor_id = store.new_visitor_id()
    return visitor_id, store.new_session_id(visitor_id)


def _use_model(monkeypatch, model):
    import bridge.agent_bridge as agent_bridge

    monkeypatch.setattr(agent_bridge, "AgentLLMModel", lambda *a, **k: model)


def test_an_upserted_page_answers_with_the_instance_pages_off(guest_env, monkeypatch):
    from agent.guest.share import feature_status

    assert feature_status()["serving"] is False
    share = _upsert()
    assert share["status"] == "active" and share["guest_md"] == "Answer product questions."
    assert _ok("get", {"slug": "web-demo"})["status"] == "active"
    assert [s["slug"] for s in _ok("list", {})["shares"]] == ["web-demo"]

    _use_model(monkeypatch, _ScriptedModel([("text", "Hello!")]))
    visitor_id, session_id = _visitor()
    result = _ok("message", {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id,
                             "text": "hi"})
    assert result["status"] == "done" and result["content"] == "Hello!"


def test_bad_ids_and_unknown_pages_are_refused(guest_env):
    assert _refused("get", {"slug": "../etc"}) == (400, "invalid_slug")
    assert _refused("upsert", {"slug": "data", "config": {}}) == (400, "invalid_slug")
    assert _refused("get", {"slug": "web-missing"}) == (404, "share_not_found")
    assert _refused("nope", {}) == (404, "unknown_action")
    assert _refused("upsert", {"slug": "web-demo", "config": "x"}) == (400, "invalid_config")


def test_a_widening_on_disk_waits_for_confirm(guest_env):
    _upsert(tools=["read"])
    path = load_profile("web-demo").path
    with open(f"{path}/config.json") as f:
        cfg = json.load(f)
    cfg["tools"] = ["read", "write"]
    with open(f"{path}/config.json", "w") as f:
        json.dump(cfg, f)

    share = _ok("get", {"slug": "web-demo"})
    assert share["effective_config"]["tools"] == ["read"]
    assert any("write" in p for p in share["pending"])
    share = _ok("confirm", {"slug": "web-demo"})
    assert share["effective_config"]["tools"] == ["read", "write"] and share["pending"] == []


def test_a_reply_streams_its_progress_without_real_paths(guest_env, monkeypatch):
    model = _ScriptedModel([
        ("tool", "read", {"path": str(guest_env / "owner-notes.md")}),
        ("tool", "write", {"path": "report.md", "content": "# Report"}),
        ("text", "Here is [your report](/work/report.md)."),
    ])
    (guest_env / "owner-notes.md").write_text("OWNER-SECRET")
    _use_model(monkeypatch, model)
    _upsert()
    visitor_id, session_id = _visitor()
    chunks = []
    result = _ok("message", {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id,
                             "text": "make me a report"}, chunks.append)

    kinds = [c["type"] for c in chunks]
    assert kinds[0] == "stream_start" and "delta" in kinds
    assert [c["tool"] for c in chunks if c["type"] == "tool_start"] == ["read", "write"]
    assert result["status"] == "done" and result["files"][0]["path"] == "/work/report.md"
    # The model named the owner's file itself, so only where /work really is
    # must stay out.
    everything = json.dumps([chunks, result], ensure_ascii=False)
    assert str(guest_env / "data") not in everything and "OWNER-SECRET" not in everything
    assert next(c for c in chunks if c["type"] == "tool_end")["status"] == "error"


def test_a_paused_page_refuses_visitors_until_it_resumes(guest_env, monkeypatch):
    _use_model(monkeypatch, _ScriptedModel([("text", "ok"), ("text", "ok")]))
    _upsert()
    visitor_id, session_id = _visitor()
    message = {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id, "text": "hi"}

    assert _ok("disable", {"slug": "web-demo"})["status"] == "disabled"
    assert _refused("message", message) == (403, "disabled")
    _ok("enable", {"slug": "web-demo"})
    assert _ok("message", message)["status"] == "done"


def test_cancel_stops_a_reply_in_progress(guest_env, monkeypatch):
    started, release = threading.Event(), threading.Event()

    class SlowModel(_ScriptedModel):
        def call_stream(self, request):
            self.requests.append(request)
            yield {"choices": [{"delta": {"content": "Working"}, "finish_reason": None}]}
            started.set()
            release.wait(10)
            yield {"choices": [{"delta": {"content": " on it"}, "finish_reason": None}]}
            yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    _use_model(monkeypatch, SlowModel([]))
    _upsert()
    visitor_id, session_id = _visitor()
    ids = {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id}
    results = []
    worker = threading.Thread(target=lambda: results.append(dispatch("message", dict(ids, text="hi"))))
    worker.start()
    assert started.wait(10)
    assert _ok("cancel", ids)["cancelled"] is True
    release.set()
    worker.join(10)
    assert results[0]["code"] == 200 and results[0]["payload"]["status"] == "cancelled"


def test_a_visitor_only_reaches_their_own_conversations(guest_env, monkeypatch):
    _use_model(monkeypatch, _ScriptedModel([("text", "ok")]))
    _upsert()
    alice, alice_session = _visitor()
    bob, _ = _visitor()
    _ok("message", {"slug": "web-demo", "visitor_id": alice, "session_id": alice_session, "text": "hi"})

    for action in ("message", "clear", "cancel", "file", "upload"):
        assert _refused(action, {"slug": "web-demo", "visitor_id": bob, "session_id": alice_session,
                                 "text": "hi", "path": "/work/x", "url": "https://example.com/a"}) \
            == (404, "session_not_found")
    assert _refused("clear", {"slug": "web-demo", "visitor_id": "A" * 24, "session_id": "A" * 36}) \
        == (404, "session_not_found")


def test_the_daily_question_limit_applies(guest_env, monkeypatch):
    _use_model(monkeypatch, _ScriptedModel([("text", "ok")]))
    _upsert(limits={"daily_messages": 1})
    visitor_id, session_id = _visitor()
    message = {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id, "text": "hi"}
    _ok("message", message)
    assert _refused("message", message) == (429, "visitor_quota")
    other_id, other_session = _visitor()
    _ok("message", {"slug": "web-demo", "visitor_id": other_id, "session_id": other_session, "text": "hi"})
    assert _ok("get", {"slug": "web-demo"})["questions_today"] == 2


def test_files_are_limited_to_the_conversation_and_what_replies_offered(guest_env, monkeypatch):
    product = guest_env / "product"
    product.mkdir()
    (product / "price.md").write_text("PRICE")
    (product / "internal.md").write_text("INTERNAL")
    _use_model(monkeypatch, _ScriptedModel([
        ("tool", "write", {"path": "notes.md", "content": "NOTES"}),
        ("text", "See /data/product/price.md."),
    ]))
    _upsert(references=[{"path": str(product), "note": "Product docs"}])
    visitor_id, session_id = _visitor()
    ids = {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id}
    _ok("message", dict(ids, text="hi"))

    import base64

    notes = _ok("file", dict(ids, path="/work/notes.md"))
    assert base64.b64decode(notes["content_b64"]) == b"NOTES" and notes["eof"] is True
    assert notes["path"] == "/work/notes.md"
    price = _ok("file", dict(ids, path="/data/product/price.md", chunk_size=2))
    assert base64.b64decode(price["content_b64"]) == b"PR" and price["eof"] is False
    for path in ("/data/product/internal.md", "/work/../../owner.md", str(product / "price.md"), ""):
        assert _refused("file", dict(ids, path=path)) == (404, "file_not_found")


class _FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]


def test_uploads_fetch_public_urls_within_the_size_limit(guest_env, monkeypatch):
    from agent.tools.utils import url_safety

    _upsert(limits={"max_upload_mb": 1})
    visitor_id, session_id = _visitor()
    ids = {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id}

    for url in ("http://127.0.0.1/a.png", "http://169.254.169.254/latest", "file:///etc/passwd"):
        assert _refused("upload", dict(ids, url=url)) == (400, "url_blocked")

    monkeypatch.setattr(url_safety, "validate_url_safe", lambda url: None)
    monkeypatch.setattr(url_safety, "safe_get", lambda url, **kw: _FakeResponse(b"x" * (1024 * 1024 + 1)))
    assert _refused("upload", dict(ids, url="https://files.example.com/big.bin")) == (413, "too_large")

    monkeypatch.setattr(url_safety, "safe_get", lambda url, **kw: _FakeResponse(b"\x89PNG"))
    saved = _ok("upload", dict(ids, url="https://files.example.com/a/b.png?sig=1", name="chart.png"))
    assert saved == {"path": "/work/uploads/chart.png", "name": "chart.png", "size": 4, "file_type": "image"}


def test_delete_removes_the_page_and_its_conversations(guest_env, monkeypatch):
    _use_model(monkeypatch, _ScriptedModel([("text", "ok")]))
    _upsert()
    visitor_id, session_id = _visitor()
    _ok("message", {"slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id, "text": "hi"})
    assert len(_ok("logs", {"slug": "web-demo"})["sessions"]) == 1
    assert _ok("log_detail", {"slug": "web-demo", "session_id": session_id})["records"]

    _ok("delete", {"slug": "web-demo"})
    assert _refused("get", {"slug": "web-demo"}) == (404, "share_not_found")
    assert store.list_sessions("web-demo") == [] and store.get_entry("web-demo") is None


def test_the_connection_routes_guest_messages_and_attributes_usage(guest_env, monkeypatch):
    from common import cloud_client
    from common.cloud_client import CloudClient

    seen_users = []

    class AttributedModel(_ScriptedModel):
        def call_stream(self, request):
            seen_users.append(cloud_client.current_user_id())
            yield from super().call_stream(request)

    _use_model(monkeypatch, AttributedModel([("text", "Hello!")]))
    _upsert()
    visitor_id, session_id = _visitor()

    client = CloudClient.__new__(CloudClient)
    sent, done = [], threading.Event()

    def send_package(msg):
        sent.append(msg)
        if not msg["data"].get("streaming"):
            done.set()

    client._send_package = send_package
    passed_on = []
    monkeypatch.setattr(cloud_client.LinkAIClient, "_dispatch_msg", lambda self, msg: passed_on.append(msg),
                        raising=False)

    client._dispatch_msg({"type": "GUEST", "requestId": "r1", "data": {"action": "message", "payload": {
        "slug": "web-demo", "visitor_id": visitor_id, "session_id": session_id, "text": "hi", "user_id": 10001}}})
    assert done.wait(10)
    assert all(m["type"] == "GUEST" and m["requestId"] == "r1" for m in sent)
    assert [m["data"]["streaming"] for m in sent][-1] is False
    assert sent[0]["data"]["payload"]["type"] == "stream_start"
    final = sent[-1]["data"]
    assert final["code"] == 200 and final["payload"]["content"] == "Hello!"
    assert seen_users == ["10001"]

    client._dispatch_msg({"type": "CHAT", "data": {}})
    assert passed_on == [{"type": "CHAT", "data": {}}]
