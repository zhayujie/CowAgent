"""The LinkAI session must honour the configured context budget.

``config.py`` caps the carried history with ``conversation_max_tokens``
("max characters of context memory"), 1000 characters by default. Every
sibling session (``chatgpt``, ``openai``, ``deepseek``, ``dashscope``,
``qianfan``, ``moonshot``, ...) loops until the history fits that cap and
drops the oldest message first, so the recent turns survive.

``LinkAISession`` overrides ``discard_exceeding`` with a loop that pops a
single ``(user, assistant)`` pair and returns, so the history stays
permanently over the budget: after a handful of turns it sits at roughly
twenty times ``conversation_max_tokens``, and every request carries that
stale context to the API.
"""

from models.linkai.link_ai_bot import LinkAISession

BUDGET = 1000  # config.py: conversation_max_tokens, in characters
TURN = 400


def _filled_session(turns=20, size=TURN):
    session = LinkAISession("chat", system_prompt="S")
    for i in range(turns):
        session.add_query(f"q{i}" + "x" * size)
        session.add_reply(f"a{i}" + "y" * size)
    return session


def test_linkai_session_trims_history_to_the_configured_budget():
    """One call must leave the history inside the configured budget."""
    session = _filled_session()
    assert session.calc_tokens() > BUDGET

    result = session.discard_exceeding(BUDGET)

    assert result <= BUDGET, f"history still {result} characters after trimming"
    assert session.calc_tokens() <= BUDGET


def test_linkai_session_drops_as_many_old_turns_as_needed():
    """Only the turns that fit may survive; the rest must be dropped."""
    session = _filled_session()
    session.discard_exceeding(BUDGET)

    # The system prompt plus at most one turn fits a 1000-character budget.
    assert len(session.messages) <= 3, (
        f"{len(session.messages)} messages survived the trim"
    )


def test_linkai_session_stays_within_budget_across_many_turns():
    """Repeated turns must not creep past the budget again."""
    session = _filled_session(turns=2)
    for i in range(30):
        session.add_query(f"q{i}" + "x" * TURN)
        session.add_reply(f"a{i}" + "y" * TURN)
        session.discard_exceeding(BUDGET)
        assert session.calc_tokens() <= BUDGET, (
            f"history grew to {session.calc_tokens()} characters"
        )


def test_linkai_session_keeps_the_most_recent_turn():
    """Trimming must drop the oldest turn, not the one just finished."""
    session = _filled_session()
    session.discard_exceeding(BUDGET)

    assert session.messages[-1]["role"] == "assistant"
    assert session.messages[-1]["content"].startswith("a19"), (
        "the newest assistant reply was dropped from the session"
    )
    assert session.messages[-2]["role"] == "user"
    assert session.messages[-2]["content"].startswith("q19"), (
        "the newest user query was dropped from the session"
    )


def test_linkai_session_drops_the_oldest_turn_first():
    """The turn that leaves the window must be the first one."""
    session = _filled_session()
    session.discard_exceeding(BUDGET)

    kept = [m["content"][:2] for m in session.messages[1:]]
    assert "q0" not in kept, "the oldest turn was kept instead of the newest"


def test_linkai_session_never_drops_the_system_prompt():
    """Control: the system prompt survives the trim."""
    session = _filled_session()
    session.discard_exceeding(BUDGET)
    assert session.messages[0]["role"] == "system"
    assert session.messages[0]["content"] == "S"


def test_linkai_session_keeps_a_question_larger_than_the_budget():
    """Control: the current question is kept so the turn can still be answered."""
    session = LinkAISession("chat", system_prompt="S")
    session.add_query("q" * (BUDGET * 2))

    result = session.discard_exceeding(BUDGET)

    assert result is not None
    assert session.messages[0]["role"] == "system"
    assert session.messages[-1]["role"] == "user"
    assert session.messages[-1]["content"].startswith("q")


def test_linkai_session_without_history_is_a_no_op():
    """Control: an empty session stays empty."""
    session = LinkAISession("chat", system_prompt="S")
    session.messages = []

    assert session.discard_exceeding(BUDGET) == 0
    assert session.messages == []


def test_linkai_session_trims_a_history_without_any_user_turn():
    """A history with no user/assistant pair must still be trimmed."""
    session = LinkAISession("chat", system_prompt="S")
    session.messages = [
        {"role": "system", "content": "S"},
        {"role": "assistant", "content": "a" * TURN},
        {"role": "assistant", "content": "b" * TURN},
    ]

    result = session.discard_exceeding(BUDGET)

    assert result <= BUDGET
    assert session.messages[0]["role"] == "system"


def test_linkai_session_keeps_the_current_turn_when_it_exceeds_the_budget():
    """The current turn is kept whole when it alone does not fit the budget."""
    session = LinkAISession("chat", system_prompt="S")
    session.add_query("q" * 600)
    session.add_reply("a" * 600)

    result = session.discard_exceeding(BUDGET)

    assert result > BUDGET, "the current turn alone was expected to exceed the budget"
    assert len(session.messages) == 3, "the current turn was not kept whole"
    assert session.messages[1]["role"] == "user"
    assert session.messages[2]["role"] == "assistant"
