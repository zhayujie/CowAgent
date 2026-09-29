"""A ghost roster must not look like a shared conversation.

Deleting an Agent used to leave its id in session_prefs.members. The shared
path then reloaded history as plain text and dropped tool_use/tool_result
pairs, so a solo WeChat chat lost its tool chain. The predicate resolves each
id; only a member that still exists counts. An id with no local profile still
counts when the installed transport lists it as a peer.
"""

import pytest

from agent.multiagent import InvokeResult, PeerAgent, PeerTransport
from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from bridge.agent_initializer import AgentInitializer


class _DirectoryOnlyTransport(PeerTransport):
    """Transport stub: directory lookups only, no hand-off."""

    def invoke(self, request, on_event=None):
        return InvokeResult.failed("directory only")


@pytest.fixture
def roster(tmp_path):
    registry = AgentRegistry(
        [
            AgentProfile("agent-real", "Real", str(tmp_path / "real")),
            AgentProfile(
                "agent-disabled", "Off", str(tmp_path / "off"), enabled=False
            ),
        ],
        default_agent_id="agent-real",
    )
    set_agent_registry(registry)
    yield registry
    set_agent_registry(None)


def _stub_members(monkeypatch, members):
    from agent.workspace import session_prefs

    monkeypatch.setattr(
        session_prefs,
        "get_prefs",
        lambda session_id, agent_id=None: {"members": members},
    )


# The default agent's real id is agent-real, so "default" only resolves
# through get_addressed. A plain get("default") would miss it.
_MATRIX = [
    pytest.param(["agent-ghost"], False, id="ghost-only"),
    pytest.param(["agent-real"], True, id="real"),
    pytest.param(["default"], True, id="default-alias"),
    pytest.param(["agent-ghost", "agent-real"], True, id="ghost-plus-real"),
    pytest.param([], False, id="empty"),
    pytest.param([None, ""], False, id="blank-entries"),
    pytest.param(["   "], False, id="whitespace"),
    pytest.param(["garbage-id"], False, id="unknown-id"),
    pytest.param(["agent-disabled"], True, id="disabled-still-exists"),
    pytest.param([None, "", "agent-real"], True, id="blanks-then-real"),
    pytest.param([None, "agent-ghost"], False, id="blank-then-ghost"),
]


@pytest.mark.parametrize(("members", "expected"), _MATRIX)
def test_is_shared_conversation_resolves_the_roster(
    roster, monkeypatch, members, expected
):
    _stub_members(monkeypatch, members)
    assert AgentInitializer._is_shared_conversation("sess", "agent-real") is expected


@pytest.mark.parametrize(("members", "expected"), _MATRIX)
def test_any_member_exists_resolves_the_roster(roster, members, expected):
    assert AgentInitializer._any_member_exists(members) is expected


def test_blank_session_is_not_shared(roster, monkeypatch):
    def boom(session_id, agent_id=None):
        raise AssertionError("prefs should not be read without a session id")

    from agent.workspace import session_prefs

    monkeypatch.setattr(session_prefs, "get_prefs", boom)
    assert AgentInitializer._is_shared_conversation("", "agent-real") is False
    assert AgentInitializer._is_shared_conversation(None, "agent-real") is False


def test_prefs_read_failure_is_not_shared(roster, monkeypatch):
    from agent.workspace import session_prefs

    def boom(session_id, agent_id=None):
        raise OSError("unreadable")

    monkeypatch.setattr(session_prefs, "get_prefs", boom)
    assert AgentInitializer._is_shared_conversation("sess", "agent-real") is False


def test_unreadable_registry_does_not_downgrade_a_roster(monkeypatch):
    """A registry that will not load must not turn a real team into a solo chat."""
    _stub_members(monkeypatch, ["agent-ghost"])

    def unavailable():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr("agent.registry.get_agent_registry", unavailable)
    assert AgentInitializer._any_member_exists(["agent-ghost"]) is True
    assert AgentInitializer._is_shared_conversation("sess", "agent-real") is True


def test_unreachable_peer_lookup_does_not_downgrade_a_roster(monkeypatch):
    """The peer half of the lookup must fail open the same way the registry does.

    ``_is_shared_conversation`` turns anything raised out of
    ``_any_member_exists`` into "not shared", so an import that blows up here
    would silently produce the very downgrade this guard exists to prevent.
    """
    import sys

    _stub_members(monkeypatch, ["agent-ghost"])
    monkeypatch.setitem(sys.modules, "agent.multiagent", None)

    assert AgentInitializer._any_member_exists(["agent-ghost"]) is True
    assert AgentInitializer._is_shared_conversation("sess", "agent-real") is True


def test_remote_only_peer_counts_as_a_member(roster, monkeypatch):
    """A hosted teammate with no local profile is still a shared roster."""
    from agent.multiagent import set_transport

    transport = _DirectoryOnlyTransport()
    transport.register_peers([PeerAgent("agent-remote", "Remote", "hosted")])
    set_transport(transport)
    try:
        assert AgentInitializer._any_member_exists(["agent-remote"]) is True
        # The same transport leaves an id it has never heard of as a ghost.
        assert AgentInitializer._any_member_exists(["agent-ghost"]) is False
        _stub_members(monkeypatch, ["agent-remote"])
        assert AgentInitializer._is_shared_conversation("sess", "agent-real") is True
    finally:
        set_transport(None)


def test_ghost_only_without_transport_is_not_shared(roster, monkeypatch):
    """No installed transport: a deleted local id is still a solo conversation."""
    from agent.multiagent import get_transport, set_transport

    set_transport(None)
    try:
        assert get_transport() is None
        assert AgentInitializer._any_member_exists(["agent-ghost"]) is False
        _stub_members(monkeypatch, ["agent-ghost"])
        assert AgentInitializer._is_shared_conversation("sess", "agent-real") is False
    finally:
        set_transport(None)
