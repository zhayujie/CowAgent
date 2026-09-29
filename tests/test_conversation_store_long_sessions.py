"""Long-session behaviour of ConversationStore: bounded restore and msg_count upkeep."""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory.conversation_store import ConversationStore


def _user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _assistant(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _tool_use(idx):
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": f"t{idx}", "name": "bash", "input": {}}],
    }


def _tool_result(idx):
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": f"t{idx}", "content": "ok"}],
    }


def _texts(messages):
    out = []
    for m in messages:
        content = m["content"]
        block = content[0] if isinstance(content, list) and content else {}
        out.append(block.get("text") or block.get("type"))
    return out


def _msg_count(store, sid):
    for s in store.list_sessions()["sessions"]:
        if s["session_id"] == sid:
            return s["msg_count"]
    return None


def _actual_count(db_path, sid):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (sid,)
        ).fetchone()[0]
    finally:
        conn.close()


def _seed(store, sid, turns):
    # A leading assistant row sits before the first visible user message, so the
    # "no more turns than the budget" case must still return it.
    store.append_messages(sid, [_assistant("greeting")])
    for i in range(turns):
        store.append_messages(
            sid,
            [_user(f"q{i}"), _tool_use(i), _tool_result(i), _assistant(f"a{i}")],
        )


def test_restore_keeps_only_the_requested_turns():
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp) / "index.db")
        _seed(store, "s", turns=6)

        msgs = store.load_messages("s", max_turns=2)

        assert _texts(msgs) == [
            "q4", "tool_use", "tool_result", "a4",
            "q5", "tool_use", "tool_result", "a5",
        ]


def test_restore_returns_everything_when_within_budget():
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp) / "index.db")
        _seed(store, "s", turns=3)

        exact = store.load_messages("s", max_turns=3)
        loose = store.load_messages("s", max_turns=10)

        assert _texts(exact) == _texts(loose)
        assert _texts(exact)[0] == "greeting"
        assert len(exact) == 1 + 3 * 4


def test_restore_honours_context_boundary():
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp) / "index.db")
        _seed(store, "s", turns=2)
        store.clear_context("s")
        store.append_messages("s", [_user("fresh"), _assistant("reply")])

        assert _texts(store.load_messages("s", max_turns=10)) == ["fresh", "reply"]


def test_msg_count_tracks_appends_and_deletes():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "index.db"
        store = ConversationStore(db)
        _seed(store, "s", turns=3)
        assert _msg_count(store, "s") == _actual_count(db, "s") == 13

        # Deleting the first turn removes its user message and the reply rows.
        store.delete_message_pair("s", user_seq=1)
        assert _msg_count(store, "s") == _actual_count(db, "s") == 9


def test_prune_scheduled_pairs_keeps_newest_and_count_in_sync():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "index.db"
        store = ConversationStore(db)
        store.append_messages("s", [_user("hello"), _assistant("hi")])
        for i in range(4):
            store.append_messages(
                "s", [_user(f"[SCHEDULED] run {i}"), _assistant(f"result {i}")]
            )

        deleted = store.prune_scheduled_messages("s", keep_last_n=1)

        assert deleted == 6
        assert _texts(store.load_messages("s", max_turns=10)) == [
            "hello", "hi", "[SCHEDULED] run 3", "result 3",
        ]
        assert _msg_count(store, "s") == _actual_count(db, "s") == 4
