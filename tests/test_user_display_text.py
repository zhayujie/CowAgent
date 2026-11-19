# encoding:utf-8
"""A user turn can carry the text the client shows in place of the message.

The agent and the stored transcript keep the full message; the history page
exposes the display text next to it and the session title is taken from it.
"""

import tempfile
from pathlib import Path

from agent.memory.conversation_store import ConversationStore
from bridge.agent_bridge import AgentBridge
from bridge.context import Context, ContextType


FULL = "You are a writing assistant. Follow the house rules...\nTopic: spring sale"
DISPLAY = "Campaign copy\nTopic: spring sale"


def _user(text, extras=None):
    message = {"role": "user", "content": [{"type": "text", "text": text}]}
    if extras:
        message["extras"] = extras
    return message


def _assistant(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def test_history_turn_exposes_display_next_to_full_content():
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp) / "index.db")
        store.append_messages("s", [_user(FULL, {"display": DISPLAY}), _assistant("done")])

        user = [m for m in store.load_history_page("s")["messages"] if m["role"] == "user"][0]

        assert user["content"] == FULL
        assert user["display"] == DISPLAY
        assert store.list_sessions()["sessions"][0]["title"] == "Campaign copy"
        assert store.list_user_messages("s")["messages"][0]["preview"].startswith("Campaign copy")


def test_plain_turn_has_no_display():
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp) / "index.db")
        store.append_messages("s", [_user("hello"), _assistant("hi")])

        user = [m for m in store.load_history_page("s")["messages"] if m["role"] == "user"][0]

        assert "display" not in user


def test_pre_persisted_user_turn_keeps_display_from_context():
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp) / "index.db")
        bridge = AgentBridge.__new__(AgentBridge)
        bridge.get_conversation_store = lambda agent_id=None: store
        context = Context(ContextType.TEXT, FULL)
        context["display"] = DISPLAY

        assert bridge._pre_persist_user_message("s", FULL, context, False)

        user = store.load_history_page("s")["messages"][0]
        assert user["content"] == FULL
        assert user["display"] == DISPLAY
