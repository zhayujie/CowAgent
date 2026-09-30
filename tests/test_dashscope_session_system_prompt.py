# encoding:utf-8
"""DashscopeSession keeps the system prompt it is built with.

``DashscopeSession.__init__`` called ``Session.__init__(session_id)`` without
the ``system_prompt`` it was given, so every session fell back to
``character_desc``. The Role plugin creates a new session with
``build_session(session_id, system_prompt=<role>)``, so on a fresh DashScope
session the chosen role was silently ignored. Every other session class
forwards the prompt.
"""
from models.dashscope.dashscope_session import DashscopeSession
from models.session_manager import SessionManager


def test_session_uses_the_given_system_prompt():
    session = DashscopeSession("s1", system_prompt="You are a cat.")

    assert session.system_prompt == "You are a cat."
    assert session.messages == [{"role": "system", "content": "You are a cat."}]


def test_session_keeps_its_model():
    assert DashscopeSession("s1", model="qwen-max").model == "qwen-max"


def test_role_prompt_applies_to_a_new_session():
    manager = SessionManager(DashscopeSession, model="qwen-plus")

    session = manager.build_session("s1", system_prompt="You are a cat.")

    assert session.messages[0]["content"] == "You are a cat."
