"""LinkAI error bodies in any shape are read without raising, and a 4xx is not retried."""

from unittest.mock import Mock, patch

import pytest

from bridge.context import Context, ContextType
from models.linkai import link_ai_bot
from tests.sleep_stub import current_thread_sleep

CONF = {"linkai_api_base": "https://api.example.test", "linkai_api_key": "test-key",
        "linkai_app_code": "app-1", "model": "gpt-4o", "channel_type": "web"}


def _response(status_code, body=None, text=""):
    response = Mock(status_code=status_code, text=text)
    if body is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body
    return response


@pytest.mark.parametrize("body,text,expected", [
    ({"code": 40001, "message": "quota exceeded"}, "", ("quota exceeded", "40001")),
    ({"detail": "Not Found"}, "", ("Not Found", "")),
    ({"error": {"message": "bad key", "type": "auth"}}, "", ("bad key", "auth")),
    (None, "<html>502</html>", ("<html>502</html>", "")),
])
def test_error_body_shapes(body, text, expected):
    assert link_ai_bot._linkai_error_body(_response(400, body, text)) == expected


@pytest.mark.parametrize("call", ["chat", "reply_text"])
def test_rejection_without_openai_error_is_not_retried(call):
    bot = link_ai_bot.LinkAIBot.__new__(link_ai_bot.LinkAIBot)
    bot.sessions = Mock(session_msg_query=lambda query, session_id: [{"role": "user", "content": query}])
    bot.args = {}
    post = Mock(return_value=_response(400, {"detail": "Not Found"}))
    with patch.object(link_ai_bot, "conf", lambda: dict(CONF)), \
            patch.object(link_ai_bot.requests, "post", post), \
            patch.object(link_ai_bot.time, "sleep", current_thread_sleep()):
        if call == "chat":
            content = bot._chat("hi", Context(ContextType.TEXT, "hi", {"session_id": "u1"})).content
        else:
            content = bot.reply_text(Mock(messages=[{"role": "user", "content": "hi"}], session_id="u1"))["content"]
    assert post.call_count == 1
    assert content == "提问太快啦，请休息一下再问我吧"
