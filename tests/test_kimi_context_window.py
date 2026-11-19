"""Kimi model metadata must reach the runtime context-budget resolver."""

import types

import pytest

from agent.protocol.agent import Agent, resolve_family_spec


@pytest.mark.parametrize(
    "model", ["kimi-k3", "kimi-k3.1-pro", "kimi-k3.1-pro-highspeed"]
)
def test_kimi_k3_and_k31_use_their_1m_context_window(model):
    assert resolve_family_spec(model) == (1048576, 131072)

    agent = object.__new__(Agent)
    agent.model = types.SimpleNamespace(model=model)

    assert agent._get_model_context_window() == 1048576


@pytest.mark.parametrize("model", ["kimi-k3", "kimi-k3.1-pro"])
def test_kimi_honors_a_smaller_user_budget_without_catalog_overrides(model):
    agent = object.__new__(Agent)
    agent.model = types.SimpleNamespace(model=model)
    agent.max_context_tokens = 262144
    agent.system_prompt = ""
    agent.get_skills_prompt = lambda: ""
    agent.tools = []
    agent.messages = []
    agent.last_usage = None

    usage = agent.get_context_usage()

    assert usage["window"] == 1048576
    assert usage["limit"] == 262144


def test_kimi_k2_keeps_the_conservative_fallback():
    assert resolve_family_spec("kimi-k2.5") == (128000, None)
