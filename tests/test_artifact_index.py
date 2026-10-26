# encoding:utf-8
"""The artifact index: which stored messages produced which files, and how the
index answers the artifact view."""

import json

from agent.memory.conversation_store import ConversationStore
from agent.protocol.artifact import collect_message_artifacts


def _touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _tool_turn(name, args, result, is_error=False, tool_id="t1"):
    return [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": name, "input": args},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id,
             "content": result if isinstance(result, str) else json.dumps(result),
             **({"is_error": True} if is_error else {})},
        ]},
    ]


def test_written_files_are_collected_and_internal_ones_are_not(tmp_path):
    _touch(tmp_path / "site" / "index.html")
    _touch(tmp_path / "memory" / "2026-10-02.md")
    messages = (
        _tool_turn("write", {"path": "site/index.html"}, {"path": "site/index.html"}, tool_id="a")
        + _tool_turn("write", {"path": "memory/2026-10-02.md"}, {"path": "memory/2026-10-02.md"}, tool_id="b")
    )
    found = collect_message_artifacts(messages, str(tmp_path))
    assert [(item["kind"], item["source"]) for item in found] == [("html", "write")]
    assert found[0]["path"].endswith("site/index.html")


def test_a_written_plan_is_an_artifact(tmp_path):
    _touch(tmp_path / "plans" / "2026-10-03-setup.md")
    messages = _tool_turn("write", {"path": "plans/2026-10-03-setup.md"}, {"path": "plans/2026-10-03-setup.md"})
    found = collect_message_artifacts(messages, str(tmp_path))
    assert [item["kind"] for item in found] == ["markdown"]
    assert found[0]["path"].endswith("plans/2026-10-03-setup.md")


def test_a_failed_write_produces_nothing(tmp_path):
    _touch(tmp_path / "a.md")
    messages = _tool_turn("write", {"path": "a.md"}, "Error: disk full", is_error=True)
    assert collect_message_artifacts(messages, str(tmp_path)) == []


def test_a_sent_file_counts_even_from_tmp(tmp_path):
    shot = _touch(tmp_path / "tmp" / "screenshot_1.png")
    messages = _tool_turn("send", {"path": "tmp/screenshot_1.png"},
                          {"type": "file_to_send", "path": str(shot)})
    found = collect_message_artifacts(messages, str(tmp_path))
    assert [(item["kind"], item["source"]) for item in found] == [("image", "send")]


def test_embedded_media_in_the_reply_is_collected(tmp_path):
    _touch(tmp_path / "images" / "cat.png")
    messages = [{"role": "assistant", "content": [
        {"type": "text", "text": "Here it is:\n\n![cat](images/cat.png)\n![x](https://e.com/a.png)"},
    ]}]
    found = collect_message_artifacts(messages, str(tmp_path))
    assert [(item["kind"], item["source"]) for item in found] == [("image", "embed")]


def test_subagent_files_are_collected(tmp_path):
    _touch(tmp_path / "out" / "report.pdf")
    messages = _tool_turn("subagent", {"tasks": []},
                          {"results": [{"files": [str(tmp_path / "out" / "report.pdf")]}]})
    found = collect_message_artifacts(messages, str(tmp_path))
    assert [(item["kind"], item["source"]) for item in found] == [("pdf", "subagent")]


def _store(tmp_path, agent_id=""):
    return ConversationStore(tmp_path / "index.db", agent_id=agent_id)


def test_rewriting_a_file_moves_it_to_the_latest_turn(tmp_path):
    store = _store(tmp_path)
    store.append_messages("s1", [{"role": "user", "content": [{"type": "text", "text": "make a page"}]}])
    store.record_artifacts("s1", [{"path": "/ws/a.html", "kind": "html", "source": "write"}])
    first = store.list_artifacts()["items"]
    assert len(first) == 1 and first[0]["turn_seq"] == 0

    store.append_messages("s1", [
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        {"role": "user", "content": [{"type": "text", "text": "make it blue"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]},
    ])
    store.record_artifacts("s1", [{"path": "/ws/a.html", "kind": "html", "source": "edit"}])
    items = store.list_artifacts()["items"]
    assert len(items) == 1
    assert items[0]["turn_seq"] == 2
    assert items[0]["source"] == "edit"
    assert items[0]["session_exists"] is True


def test_listing_is_scoped_by_agent_and_kind(tmp_path):
    default = _store(tmp_path)
    research = _store(tmp_path, agent_id="research")
    default.record_artifacts("s1", [{"path": "/ws/a.png", "kind": "image"}])
    research.record_artifacts("s2", [{"path": "/r/b.html", "kind": "html"}])

    assert [i["path"] for i in default.list_artifacts()["items"]] == ["/ws/a.png"]
    both = default.list_artifacts(agent_ids=["", "research"])["items"]
    assert {i["path"] for i in both} == {"/ws/a.png", "/r/b.html"}
    only_pages = default.list_artifacts(agent_ids=["", "research"], kinds=["html"])["items"]
    assert [i["agent_id"] for i in only_pages] == ["research"]
    assert default.list_artifacts(agent_ids=[])["items"] == []


def test_search_and_paging(tmp_path):
    store = _store(tmp_path)
    store.record_artifacts("s1", [{"path": f"/ws/f_{i}.md", "kind": "markdown"} for i in range(5)])
    page = store.list_artifacts(limit=2)
    assert len(page["items"]) == 2 and page["has_more"] is True
    assert [i["path"] for i in store.list_artifacts(query="f_3")["items"]] == ["/ws/f_3.md"]
    # LIKE wildcards in the query are literal.
    assert store.list_artifacts(query="f%")["items"] == []


def test_deleting_an_entry_only_touches_its_own_agent(tmp_path):
    default = _store(tmp_path)
    research = _store(tmp_path, agent_id="research")
    research.record_artifacts("s2", [{"path": "/r/b.html", "kind": "html"}])
    entry = research.list_artifacts()["items"][0]
    assert default.delete_artifact(entry["id"]) is False
    assert research.delete_artifact(entry["id"]) is True
    assert research.list_artifacts()["items"] == []


def test_an_explicit_turn_overrides_the_latest_one(tmp_path):
    store = _store(tmp_path)
    store.append_messages("s1", [
        {"role": "user", "content": [{"type": "text", "text": "one"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "user", "content": [{"type": "text", "text": "two"}]},
    ])
    store.record_artifacts("s1", [{"path": "/ws/a.html", "kind": "html"}], turn_seq=0)
    assert store.list_artifacts()["items"][0]["turn_seq"] == 0


def test_the_table_carries_no_constraint_that_would_force_a_rebuild(tmp_path):
    import sqlite3

    _store(tmp_path)
    conn = sqlite3.connect(tmp_path / "index.db")
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='artifacts'"
        ).fetchone()[0].upper()
        auto_indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='artifacts' AND name LIKE 'sqlite_autoindex%'"
        ).fetchall()
    finally:
        conn.close()
    assert "UNIQUE" not in sql and "NOT NULL" not in sql and "CHECK" not in sql
    assert auto_indexes == []


def test_a_table_from_before_pin_and_title_gained_them(tmp_path):
    import sqlite3

    # The shape the artifacts table had before pin/rename shipped: created by an
    # install that ran the console in between, then reopened on the newer code.
    conn = sqlite3.connect(tmp_path / "index.db")
    conn.execute(
        "CREATE TABLE artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, "
        "session_id TEXT, turn_seq INTEGER, path TEXT, kind TEXT, size INTEGER, "
        "source TEXT, created_at INTEGER, updated_at INTEGER, extras TEXT)"
    )
    conn.commit()
    conn.close()

    store = _store(tmp_path)
    store.record_artifacts("s1", [{"path": "/ws/a.md", "kind": "markdown"}])
    conn = sqlite3.connect(tmp_path / "index.db")
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)")}
    finally:
        conn.close()
    assert {"pinned_at", "title"} <= cols

    item = store.list_artifacts()["items"][0]
    assert item["pinned_at"] == 0 and item["title"] == ""
    assert store.set_artifact_pinned(item["id"], True) > 0
    assert store.set_artifact_title(item["id"], "release notes") is True
    assert store.list_artifacts(query="release")["items"][0]["path"] == "/ws/a.md"


def test_pinned_artifacts_lead_the_timeline(tmp_path, monkeypatch):
    import agent.memory.conversation_store as cs

    clock = iter(range(1000, 2000, 10))
    monkeypatch.setattr(cs.time, "time", lambda: next(clock))
    store = _store(tmp_path)
    for name in ("old", "mid", "new"):
        store.record_artifacts("s1", [{"path": f"/ws/{name}.md", "kind": "markdown"}])
    ids = {i["path"]: i["id"] for i in store.list_artifacts()["items"]}

    store.set_artifact_pinned(ids["/ws/old.md"], True)
    store.set_artifact_pinned(ids["/ws/mid.md"], True)
    order = [i["path"] for i in store.list_artifacts()["items"]]
    # Latest pin on top, then the rest newest first.
    assert order == ["/ws/mid.md", "/ws/old.md", "/ws/new.md"]

    # Producing the file again keeps it pinned.
    store.record_artifacts("s1", [{"path": "/ws/old.md", "kind": "markdown"}])
    assert store.list_artifacts(path="/ws/old.md")["items"][0]["pinned_at"] > 0

    assert store.set_artifact_pinned(ids["/ws/mid.md"], False) == 0
    order = [i["path"] for i in store.list_artifacts()["items"]]
    assert order == ["/ws/old.md", "/ws/new.md", "/ws/mid.md"]


def test_pinning_is_scoped_to_the_agent(tmp_path):
    default = _store(tmp_path)
    research = _store(tmp_path, agent_id="research")
    research.record_artifacts("s2", [{"path": "/r/b.html", "kind": "html"}])
    rid = research.list_artifacts()["items"][0]["id"]

    assert default.set_artifact_pinned(rid, True) is None
    assert research.list_artifacts()["items"][0]["pinned_at"] == 0


def test_a_title_names_the_entry_without_touching_the_file(tmp_path):
    store = _store(tmp_path)
    store.record_artifacts("s1", [{"path": "/ws/out/report_v3.md", "kind": "markdown"}])
    aid = store.list_artifacts()["items"][0]["id"]

    assert store.set_artifact_title(aid, "  Q3 review  ") is True
    item = store.list_artifacts()["items"][0]
    assert item["title"] == "Q3 review" and item["path"] == "/ws/out/report_v3.md"

    # Search finds it by either name, and producing the file again keeps the title.
    assert [i["id"] for i in store.list_artifacts(query="review")["items"]] == [aid]
    assert [i["id"] for i in store.list_artifacts(query="report_v3")["items"]] == [aid]
    store.record_artifacts("s1", [{"path": "/ws/out/report_v3.md", "kind": "markdown"}])
    assert store.list_artifacts()["items"][0]["title"] == "Q3 review"

    assert store.set_artifact_title(aid, "") is True
    assert store.list_artifacts()["items"][0]["title"] == ""


def test_renaming_is_scoped_to_the_agent(tmp_path):
    default = _store(tmp_path)
    research = _store(tmp_path, agent_id="research")
    research.record_artifacts("s2", [{"path": "/r/b.html", "kind": "html"}])
    rid = research.list_artifacts()["items"][0]["id"]

    assert default.set_artifact_title(rid, "mine") is False
    assert research.list_artifacts()["items"][0]["title"] == ""


# ---------------------------------------------------------------------------
# Files changed by a shell command
# ---------------------------------------------------------------------------

def test_a_command_is_credited_with_the_files_it_named_and_changed(tmp_path):
    import os

    from agent.protocol.artifact import files_changed_by_command, snapshot_command_files

    page = _touch(tmp_path / "websites" / "plan.html", "<p>old</p>")
    _touch(tmp_path / "websites" / "other.html")
    _touch(tmp_path / "memory" / "m.md")
    backup = tmp_path.parent / f"{tmp_path.name}-plan.bak.html"
    command = (
        f"cd {tmp_path}/websites && cp plan.html {backup} && python3 - <<'PY'\n"
        "p='plan.html'\nopen(p,'w').write(open(p).read().replace('old','newer'))\n"
        "open('fresh.html','w').write('hi')\nPY\n"
        f"echo \"see（websites/other.html）\" >> {tmp_path}/memory/m.md"
    )
    before = snapshot_command_files(command, str(tmp_path))
    page.write_text("<p>newer</p>", encoding="utf-8")
    _touch(tmp_path / "websites" / "fresh.html", "hi")
    _touch(backup, "<p>old</p>")
    _touch(tmp_path / "memory" / "m.md", "y")

    found = files_changed_by_command(command, str(tmp_path), before)
    # Unchanged, internal (memory/) and out-of-workspace files are all left out.
    assert found == [os.path.realpath(page), os.path.realpath(tmp_path / "websites" / "fresh.html")]


def test_a_command_that_only_reads_a_file_reports_nothing(tmp_path):
    from agent.protocol.artifact import files_changed_by_command, snapshot_command_files

    _touch(tmp_path / "site" / "q4.html")
    command = "cat site/q4.html"
    before = snapshot_command_files(command, str(tmp_path))
    assert files_changed_by_command(command, str(tmp_path), before) == []


def test_bash_results_feed_the_index_and_survive_a_truncated_tail(tmp_path):
    from agent.protocol.artifact import command_files_from_result

    page = _touch(tmp_path / "site" / "q4.html")
    result = json.dumps({"files_written": [str(page)], "output": "x" * 500})
    found = collect_message_artifacts(
        _tool_turn("bash", {"command": "python3 build.py"}, result), str(tmp_path)
    )
    assert [(item["kind"], item["source"]) for item in found] == [("html", "bash")]
    assert command_files_from_result(result[:200]) == [str(page)]
    assert command_files_from_result('{"output": "no files"}') == []


def test_history_cards_include_sent_documents_but_not_inline_media(tmp_path, monkeypatch):
    from channel.web.api import sessions

    doc = _touch(tmp_path / "docs" / "guide.docx")
    shot = _touch(tmp_path / "tmp" / "shot.png")
    clip = _touch(tmp_path / "tmp" / "voice.mp3")
    monkeypatch.setattr(sessions, "_get_workspace_root", lambda *a: str(tmp_path))

    def sent(path, file_type):
        return {"type": "tool", "name": "send", "arguments": {"path": str(path)},
                "result": json.dumps({"type": "file_to_send", "path": str(path), "file_type": file_type})}

    cards = sessions._artifacts_from_steps(
        [sent(doc, "document"), sent(shot, "image"), sent(clip, "audio")], session_id="s1",
    )
    assert [(c["file_name"], c["rel_path"], c["kind"]) for c in cards] == [
        ("guide.docx", "docs/guide.docx", "office")]
    # The web history drops the step's download link only for a path carded here.
    assert cards[0]["abs_path"] == str(doc)


def test_a_sent_file_without_a_card_is_left_to_the_download_link(tmp_path, monkeypatch):
    from channel.web.api import sessions

    hidden = _touch(tmp_path / ".notes.docx")
    gone = tmp_path / "gone.docx"
    monkeypatch.setattr(sessions, "_get_workspace_root", lambda *a: str(tmp_path))
    steps = [
        {"type": "tool", "name": "send", "arguments": {"path": str(p)},
         "result": json.dumps({"type": "file_to_send", "path": str(p), "file_type": "document"})}
        for p in (hidden, gone)
    ]

    assert sessions._artifacts_from_steps(steps, session_id="s1") == []


def test_the_live_send_event_carries_what_a_file_card_needs(tmp_path):
    from agent.protocol.agent_stream import AgentStreamExecutor

    doc = _touch(tmp_path / "docs" / "guide.docx", "data")
    stream = AgentStreamExecutor.__new__(AgentStreamExecutor)
    stream.agent = type("A", (), {"effective_cwd": lambda self: str(tmp_path)})()
    data = stream._sent_file_event({"type": "file_to_send", "path": str(doc), "file_name": "guide.docx"})
    assert (data["rel_path"], data["kind"], data["size"]) == ("docs/guide.docx", "office", 4)


def test_history_cards_include_files_a_command_changed(tmp_path, monkeypatch):
    from channel.web.api import sessions

    page = _touch(tmp_path / "site" / "q4.html")
    monkeypatch.setattr(sessions, "_get_workspace_root", lambda *a: str(tmp_path))
    steps = [{
        "type": "tool", "name": "bash", "arguments": {"command": "python3 x.py"},
        "result": json.dumps({"files_written": [str(page)], "output": ""}),
    }]
    cards = sessions._artifacts_from_steps(steps, session_id="s1")
    assert [c["file_name"] for c in cards] == ["q4.html"]
