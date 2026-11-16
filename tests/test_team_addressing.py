"""Matching a leading @mention against a conversation's roster.

Channel-agnostic: the Web console and IM channels (Feishu, ...) all decide who
a turn is addressed to with the same rule, so a name resolves the same way
whether it was typed in a browser or an IM group.
"""

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from agent.team_addressing import addressed_agent_id, roster_from_members


ROSTER = [
    {"id": "leader", "name": "队长"},
    {"id": "ops", "name": "运维"},
    {"id": "ops-lead", "name": "运维主管"},
]


def test_leading_mention_by_name():
    assert addressed_agent_id("@运维 帮我查一下", ROSTER) == "ops"


def test_leading_mention_by_id():
    assert addressed_agent_id("@ops please help", ROSTER) == "ops"


def test_longest_label_wins_when_names_overlap():
    # "运维主管" contains "运维"; the longer, exact label must win.
    assert addressed_agent_id("@运维主管 处理下", ROSTER) == "ops-lead"


def test_mention_must_lead():
    # Naming someone mid-sentence is talking about them, not handing the turn.
    assert addressed_agent_id("帮我 @运维 一下", ROSTER) == ""


def test_no_mention_returns_empty():
    assert addressed_agent_id("你好", ROSTER) == ""


def test_unknown_name_returns_empty():
    assert addressed_agent_id("@财务 报销", ROSTER) == ""


def test_empty_roster_returns_empty():
    assert addressed_agent_id("@ops hi", []) == ""


def test_boundary_requires_separator_or_end():
    # "@opsx" is not "@ops": a bare prefix must not match a different name.
    assert addressed_agent_id("@opsx hi", ROSTER) == ""
    # colon / comma / whitespace / CJK punctuation all count as a boundary
    assert addressed_agent_id("@ops：查一下", ROSTER) == "ops"
    assert addressed_agent_id("@ops", ROSTER) == "ops"


def test_sentence_ending_punctuation_is_a_boundary():
    assert addressed_agent_id("@运维。帮我查", ROSTER) == "ops"
    assert addressed_agent_id("@运维！停下", ROSTER) == "ops"
    assert addressed_agent_id("@运维？在吗", ROSTER) == "ops"
    assert addressed_agent_id("@运维；继续", ROSTER) == "ops"
    assert addressed_agent_id("@ops! stop", ROSTER) == "ops"


def test_strip_address_drops_the_boundary_punctuation():
    from agent.team_addressing import strip_address

    assert strip_address("@运维。帮我查日志", ["运维", "ops"]) == "帮我查日志"
    assert strip_address("@ops, check logs", ["运维", "ops"]) == "check logs"
    assert strip_address("@运维。", ["运维", "ops"]) == "@运维。"


@pytest.mark.parametrize("query", ["@opsx hi", "@ops.com hi", "@ops-lead hi", "  @OPS_extra hi", "@运维主管 帮我查"])
def test_strip_address_preserves_a_label_prefix(query):
    from agent.team_addressing import strip_address

    assert strip_address(query, ["ops", "运维"]) == query


def test_strip_address_matches_the_longest_complete_label():
    from agent.team_addressing import strip_address

    assert strip_address("@ops-lead: hi", ["ops", "ops-lead"]) == "hi"
    assert strip_address("@ops-leader hi", ["ops", "ops-lead"]) == "@ops-leader hi"


def test_dot_is_not_a_boundary_to_keep_domain_names():
    # "@ops.com" must not resolve to the "ops" teammate; "." stays excluded.
    assert addressed_agent_id("@ops.com 你好", ROSTER) == ""


@pytest.fixture
def registry(tmp_path):
    """A team whose default agent was given an id at provisioning time.

    That is the configuration the reserved ``"default"`` alias exists for: the
    id stays stable and meaningful, but a caller still has to be able to reach
    the agent without knowing it.
    """
    pinned = AgentRegistry(
        [
            AgentProfile("agent-abc", "CowAgent", str(tmp_path / "cow")),
            AgentProfile("ops", "Ops", str(tmp_path / "ops")),
        ],
        default_agent_id="agent-abc",
    )
    set_agent_registry(pinned)
    try:
        yield pinned
    finally:
        # ``None``, not the instance: pinning one back would outlive the test.
        set_agent_registry(None)


def test_a_member_invited_by_the_default_alias_stays_on_the_roster(registry):
    """Inviting the default agent has to make it addressable, not drop it.

    Members arrive as the ids a caller may address an Agent by, and
    ``"default"`` is one of them even when the agent's real id is not. Reading
    it with ``get`` raises on the alias, so the entry fell out as unknown and
    the conversation showed a team of one — with no error to explain why.
    """
    roster = roster_from_members("ops", ["default"])

    assert [item["id"] for item in roster] == ["ops", "agent-abc"]
    # Reachable by what a roster carries: the display name, or the real id.
    assert addressed_agent_id("@CowAgent hi", roster) == "agent-abc"
    assert addressed_agent_id("@agent-abc hi", roster) == "agent-abc"


def test_the_same_teammate_named_by_alias_and_id_appears_once(registry):
    """Both labels are the one agent, so dedupe on the resolved id.

    Comparing the raw input against the stored entry cannot see that: the
    string ``"default"`` never equals ``"agent-abc"``, so the roster would
    carry two entries for a single agent and the matcher two labels for it.
    """
    roster = roster_from_members("ops", ["default", "agent-abc"])

    assert [item["id"] for item in roster] == ["ops", "agent-abc"]


def test_the_web_console_roster_resolves_the_default_alias_too(registry):
    """The Web console keeps its own copy of this rule, and it has to match.

    ``agent.team_addressing.roster_from_members`` and
    ``channel.web.core._common._roster_from_members`` are two implementations
    of one roster, so a fix in one that misses the other leaves the browser and
    an IM group disagreeing about who is reachable.
    """
    from channel.web.core._common import _roster_from_members

    roster = _roster_from_members("ops", ["default"])

    assert [item["id"] for item in roster] == ["ops", "agent-abc"]


def test_the_alias_is_deduped_whichever_order_it_arrives_in(registry):
    """Dedupe must not depend on the alias being the first of the two names.

    Comparing the raw input against the entries already collected happens to
    catch ``["default", "agent-abc"]`` -- by then the roster holds the resolved
    id, which the second name matches literally. The reverse order is the case
    only a resolved key can see, and it is the order a member list grows in:
    the agent is invited by id, then the alias arrives from an older row.
    """
    from channel.web.core._common import _roster_from_members

    members = ["agent-abc", "default"]

    assert [item["id"] for item in roster_from_members("ops", members)] == ["ops", "agent-abc"]
    assert [item["id"] for item in _roster_from_members("ops", members)] == ["ops", "agent-abc"]


def test_the_session_team_panel_resolves_the_default_alias_too(registry):
    """The panel the user actually clicks is a third copy of the same rule.

    ``channel.web.api.sessions._session_team_state`` badges the member list for
    the console's team menu. Left unresolved, the alias is reported as an
    unknown id: a row named ``"default"``, marked unavailable, for a teammate
    the conversation can already reach -- and because the menu subtracts the
    member ids it was given from the invitable list, the agent behind the alias
    is still offered as somebody left to invite.
    """
    from channel.web.api.sessions import _session_team_state

    state = _session_team_state({"members": ["default"]}, "ops")

    assert [member["id"] for member in state["members"]] == ["agent-abc"]
    assert state["members"][0]["name"] == "CowAgent"
    assert state["members"][0]["available"] is True


def test_the_session_team_panel_lists_one_row_per_teammate(registry):
    """Same dedupe rule as the roster: two names for one agent are one row."""
    from channel.web.api.sessions import _session_team_state

    state = _session_team_state({"members": ["agent-abc", "default"]}, "ops")

    assert [member["id"] for member in state["members"]] == ["agent-abc"]


def test_the_session_team_panel_reports_an_owner_addressed_by_alias(registry):
    """Reading the owner with ``get`` raised on the alias, so the whole settings
    response failed -- the panel could not be drawn at all for a conversation
    opened by the documented ``"default"`` id."""
    from channel.web.api.sessions import _session_team_state

    state = _session_team_state({"members": ["ops"]}, "default")

    assert state["owner"]["id"] == "agent-abc"
    # The owner is not offered as a teammate to invite into its own conversation.
    assert [item["id"] for item in state["candidates"]] == ["ops"]
