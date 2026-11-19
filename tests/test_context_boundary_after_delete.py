"""New replies stay usable after deleting history below a cleared boundary."""

import sqlite3

import pytest

from agent.memory.conversation_store import ConversationStore


@pytest.mark.parametrize("agent_id", ["", "helper"])
@pytest.mark.parametrize("operation", ["edit", "delete", "regenerate"])
def test_append_after_deleting_cleared_turns_remains_in_context(
    tmp_path, agent_id, operation
):
    path = tmp_path / "history.db"
    store = ConversationStore(path, agent_id=agent_id)
    store.append_messages(
        "chat",
        [
            {"role": "user", "content": "old question one"},
            {"role": "assistant", "content": "old answer one"},
            {"role": "user", "content": "old question two"},
            {"role": "assistant", "content": "old answer two"},
        ],
    )
    assert store.clear_context("chat") == 4
    if operation == "edit":
        assert store.delete_message_pair("chat", 0, cascade=True) == 4
    elif operation == "delete":
        assert store.delete_message_pair("chat", 2) == 2
    else:
        assert store.delete_message_pair("chat", 2, delete_user=False) == 1
    new_messages = [
        {"role": "user", "content": "new request"},
        {"role": "assistant", "content": "new answer"},
    ]
    store.append_messages("chat", new_messages)
    assert store.load_messages("chat") == new_messages
    assert store.get_context_start_seq("chat") == 4
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT seq FROM messages WHERE agent_id = ? AND session_id = ? "
            "AND content IN (?, ?) ORDER BY seq",
            (agent_id, "chat", '"new request"', '"new answer"'),
        ).fetchall()
    assert rows == [(4,), (5,)]


def test_new_append_does_not_reintroduce_retained_cleared_history(tmp_path):
    store = ConversationStore(tmp_path / "history.db")
    store.append_messages("chat", [{"role": "user", "content": "cleared secret"}])
    assert store.clear_context("chat") == 1
    current = [{"role": "user", "content": "fresh"}]
    store.append_messages("chat", current)
    assert store.load_messages("chat") == current
    store.append_messages("other", [{"role": "user", "content": "unrelated"}])
    assert store.latest_seq("other") == 0
