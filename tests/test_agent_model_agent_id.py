"""The calling agent's id reaches only the bots that declare they take it.

Some bots pass unknown keyword arguments straight through to their provider,
so the id must not be handed to a bot that has not opted in.
"""

import types

import pytest

from bridge.agent_bridge import AgentLLMModel


class _Bot:
    def __init__(self, accepts):
        if accepts:
            self.accepts_agent_id = True
        self.calls = []

    def call_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return {}


def _model(bot, monkeypatch):
    model = AgentLLMModel.__new__(AgentLLMModel)
    model.agent_id = "research"
    model.session_id = "s1"
    monkeypatch.setattr(AgentLLMModel, "bot", property(lambda self: bot))
    monkeypatch.setattr(AgentLLMModel, "model", property(lambda self: "m"))
    monkeypatch.setattr(AgentLLMModel, "_is_thinking_only_model", lambda self: False)
    monkeypatch.setattr(AgentLLMModel, "_format_response", lambda self, r: r)
    return model


def _request():
    return types.SimpleNamespace(messages=[], tools=None, max_tokens=None, system=None)


@pytest.mark.parametrize("accepts", [True, False])
def test_agent_id_is_forwarded_only_to_a_bot_that_takes_it(accepts, monkeypatch):
    bot = _Bot(accepts)
    _model(bot, monkeypatch).call(_request())
    assert ("agent_id" in bot.calls[0]) is accepts
    if accepts:
        assert bot.calls[0]["agent_id"] == "research"


def test_the_bundled_bot_that_takes_it_declares_so():
    from models.linkai.link_ai_bot import LinkAIBot

    assert LinkAIBot.accepts_agent_id is True
