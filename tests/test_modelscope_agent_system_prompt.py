# encoding:utf-8
"""call_with_tools must send the agent's system prompt to ModelScope."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.modelscope.modelscope_bot import ModelScopeBot


def _bot():
    bot = ModelScopeBot.__new__(ModelScopeBot)
    bot.args = {"model": "Qwen/Qwen3-8B"}
    bot.sessions = MagicMock()
    bot.sessions.session_query.return_value = MagicMock(messages=[])
    bot._last_context = None
    return bot


def _sent(bot, messages, **kwargs):
    with patch.object(bot, "_handle_stream_response", return_value=iter(())) as handler:
        bot.call_with_tools(messages, stream=True, **kwargs)
    session, args = handler.call_args[0]
    return session.messages, args


def test_system_prompt_is_prepended_to_messages():
    user = {"role": "user", "content": "hello"}
    sent, args = _sent(_bot(), [user], system="You are a cat.")
    assert sent == [{"role": "system", "content": "You are a cat."}, user]
    assert "system" not in args


def test_existing_system_message_is_replaced_not_duplicated():
    user = {"role": "user", "content": "hello"}
    sent, _ = _sent(_bot(), [{"role": "system", "content": "old"}, user], system="new")
    assert sent == [{"role": "system", "content": "new"}, user]


def test_callers_message_list_is_not_mutated():
    messages = [{"role": "user", "content": "hello"}]
    _sent(_bot(), messages, system="You are a cat.")
    assert messages == [{"role": "user", "content": "hello"}]


def test_without_system_messages_are_unchanged():
    messages = [{"role": "user", "content": "hello"}]
    sent, _ = _sent(_bot(), messages)
    assert sent == messages
