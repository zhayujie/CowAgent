import threading
import time

import pytest

from agent.registry import AgentProfile, AgentRegistry
from agent.tools.agent_delegate.agent_delegate import (
    AgentDelegateTool,
    DelegationPolicy,
    attach_agent_delegate_to_tool,
)
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType


def _registry(disable_research=False):
    return AgentRegistry(
        [
            AgentProfile("primary", "Primary", "/tmp/delegate-primary"),
            AgentProfile(
                "research",
                "Research",
                "/tmp/delegate-research",
                enabled=not disable_research,
            ),
        ],
        "primary",
    )


def _context(agent_id="primary", session_id="user-session", **values):
    context = Context(ContextType.TEXT, "source turn", kwargs={})
    context["agent_id"] = agent_id
    context["session_id"] = session_id
    for key, value in values.items():
        context[key] = value
    return context


@pytest.fixture(autouse=True)
def _team_members(monkeypatch):
    """Make every conversation a team of primary + research by default.

    Targets are bounded to the conversation's members, read from session_prefs.
    Rather than touch the real store, stub the read so tests declare the roster
    inline; individual tests override ``roster`` to model a solo conversation.
    """
    roster = {"members": ["primary", "research"]}

    def fake_get_prefs(session_id, agent_id=None):
        return dict(roster)

    from agent.workspace import session_prefs

    monkeypatch.setattr(session_prefs, "get_prefs", fake_get_prefs)
    return roster


class FakeBridge:
    def __init__(self, registry=None):
        self.agent_registry = registry or _registry()
        self.calls = []

    @staticmethod
    def _cancel_key(agent_id, token, default_agent_id):
        return token if agent_id == default_agent_id else f"{agent_id}::{token}"

    def agent_reply(self, query, context=None, on_event=None):
        self.calls.append((query, context, on_event))
        return Reply(ReplyType.TEXT, "delegated result")


def _tool(bridge=None, config=None, context=None):
    tool = AgentDelegateTool(config=config)
    attach_agent_delegate_to_tool(
        tool,
        bridge or FakeBridge(),
        context or _context(),
    )
    return tool


def test_policy_defaults_to_other_agents_and_honors_allowlist():
    default = DelegationPolicy.from_config({})
    assert default.allows("primary", "research") is True
    assert default.allows("primary", "primary") is False

    restricted = DelegationPolicy.from_config(
        {"allowed_targets": {"primary": ["research"], "research": []}}
    )
    assert restricted.allows("primary", "research") is True
    assert restricted.allows("research", "primary") is False


def test_policy_timeout_defaults_to_ten_minutes():
    assert DelegationPolicy.from_config({}).timeout_seconds == 600.0


def test_delegate_runs_target_with_source_attribution_and_private_relay_session():
    bridge = FakeBridge()
    tool = _tool(bridge=bridge)

    result = tool.execute({"agent_id": "research", "task": "Check the evidence"})

    assert result.status == "success"
    assert result.result["agent_id"] == "research"
    assert result.result["delegated_by"] == "primary"
    assert result.result["status"] == "done"
    assert result.result["content"] == "delegated result"
    query, context, on_event = bridge.calls[0]
    assert "Delegated by Agent 'Primary' (primary)" in query
    assert context.get("agent_id") == "research"
    assert context.get("channel_type") == "agent"
    assert context.get("is_delegated_task") is True
    assert context.get("delegation_trace") == ["primary", "research"]
    assert context.get("session_id").startswith("delegate_primary_research_")
    # The teammate's run is now watched so its steps can be shown live.
    assert callable(on_event)
    # A human-readable summary rides alongside the JSON the model reads.
    assert result.display is not None
    assert "Primary → Research" in result.display
    assert "delegated result" in result.display


def test_delegate_rejects_targets_outside_the_conversation_and_lists_the_real_ones(
    _team_members,
):
    _team_members["members"] = ["primary"]  # research is not a teammate here
    tool = _tool()

    result = tool.execute({"agent_id": "research", "task": "Do work"})

    assert result.status == "error"
    assert "is not a teammate you can delegate to" in result.result
    # The error names the actual options so the model can correct itself. Here
    # only the source is a member, so there is no one to delegate to.
    assert "no teammates you can delegate to" in result.result


def test_delegate_error_names_the_available_teammates(_team_members):
    _team_members["members"] = ["research"]
    tool = _tool()

    result = tool.execute({"agent_id": "missing", "task": "Do work"})

    assert result.status == "error"
    assert "is not a teammate you can delegate to" in result.result
    # The hint names ids plainly, without the "@" the roster shows.
    assert "Research (research)" in result.result
    assert "@research" not in result.result


def test_delegate_accepts_an_agent_id_with_a_leading_at_sign():
    """The roster shows ids as "@id", so a model often passes the "@" too."""
    bridge = FakeBridge()
    tool = _tool(bridge=bridge)

    result = tool.execute({"agent_id": "@research", "task": "Check it"})

    assert result.status == "success"
    assert result.result["agent_id"] == "research"


def test_delegate_passes_the_team_roster_down_the_chain(_team_members):
    """The delegated turn carries the team so it can hand work onward.

    Its private session has no roster of its own, so the source seeds the
    downstream context with the whole team, minus whoever is already in the
    chain — the cycle guard, not the roster, stops loops. Here primary hands
    to research; designer stays reachable for research's own next hop, while
    primary (now in the chain) drops out.
    """
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", "/tmp/delegate-primary"),
            AgentProfile("research", "Research", "/tmp/delegate-research"),
            AgentProfile("designer", "Designer", "/tmp/delegate-designer"),
        ],
        "primary",
    )
    _team_members["members"] = ["research", "designer"]
    bridge = FakeBridge(registry=registry)
    tool = _tool(bridge=bridge)

    tool.execute({"agent_id": "research", "task": "Look into it"})

    _, context, _ = bridge.calls[0]
    # designer is still reachable; primary is in the chain and drops out.
    # research (the downstream itself) is filtered when it resolves its roster.
    assert context.get("delegation_members") == ["designer", "research"]


def test_delegate_reads_the_inherited_roster_when_the_session_has_none():
    """A downstream hop resolves teammates from the inherited roster.

    On a delegated turn session_prefs holds no members for the source's private
    session; the team travels in ``delegation_members`` instead, and that is
    what bounds who the source may reach.
    """
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", "/tmp/delegate-primary"),
            AgentProfile("research", "Research", "/tmp/delegate-research"),
            AgentProfile("designer", "Designer", "/tmp/delegate-designer"),
        ],
        "primary",
    )
    bridge = FakeBridge(registry=registry)
    # research is mid-chain, delegating onward to designer; its own session has
    # no roster, so the team must come from the inherited context.
    context = _context(
        agent_id="research",
        session_id="delegate_primary_research_abc",
        delegation_members=["primary", "designer"],
        delegation_trace=["primary", "research"],
        delegation_root_session="user-session",
    )
    tool = _tool(bridge=bridge, context=context)

    ok = tool.execute({"agent_id": "designer", "task": "Make a banner"})
    assert ok.status == "success"
    assert ok.result["agent_id"] == "designer"

    # primary is in the trace, so the cycle guard refuses it even though it is
    # an inherited teammate.
    looped = tool.execute({"agent_id": "primary", "task": "Loop back"})
    assert looped.status == "error"


def test_guest_speaker_delegates_under_its_own_identity_and_can_reach_the_host(
    _team_members,
):
    """A guest answering the turn delegates as itself and may hand work to the host.

    The user addressed a teammate by name, so the guest (``speaker_agent_id``)
    speaks while routing has overwritten ``agent_id`` with the conversation
    host. Delegation must run under the guest's identity — not the host's — and
    the host must be a reachable teammate, mirroring the prompt roster
    ``[host, *members]``. Without this the guest hands work to the host and the
    tool rejects it as "not a teammate" (the reported bug).
    """
    bridge = FakeBridge()
    # research is the guest speaking; primary is the host (owner) it answers for.
    _team_members["members"] = ["research"]
    context = _context(agent_id="primary", speaker_agent_id="research")
    tool = _tool(bridge=bridge, context=context)

    result = tool.execute({"agent_id": "primary", "task": "Please cover the intro"})

    assert result.status == "success"
    assert result.result["agent_id"] == "primary"
    # Attribution is the guest, not the host whose conversation this is.
    assert result.result["delegated_by"] == "research"
    query, delegated_context, _ = bridge.calls[0]
    assert "Delegated by Agent 'Research' (research)" in query
    assert delegated_context.get("delegation_trace") == ["research", "primary"]


def test_guest_speaker_cannot_delegate_to_itself(_team_members):
    """The guest may reach the host and other members, but never itself."""
    _team_members["members"] = ["research"]
    context = _context(agent_id="primary", speaker_agent_id="research")
    tool = _tool(context=context)

    result = tool.execute({"agent_id": "research", "task": "Do it yourself"})

    assert result.status == "error"
    assert "is not a teammate you can delegate to" in result.result
    # The host is offered as a real option; the guest itself is not.
    assert "Primary (primary)" in result.result


def test_delegate_rejects_unknown_targets_as_non_teammates():
    tool = _tool()
    result = tool.execute({"agent_id": "missing", "task": "Do work"})
    assert result.status == "error"
    # Unknown ids are simply not teammates; the roster is offered instead.
    assert "is not a teammate you can delegate to" in result.result


def test_delegate_honors_the_allowlist_by_hiding_disallowed_teammates():
    # research is a member, but the ACL forbids primary -> research, so it is
    # not offered and delegating to it is refused as a non-teammate.
    denied = _tool(config={"allowed_targets": {"primary": []}})
    result = denied.execute({"agent_id": "research", "task": "Do work"})
    assert result.status == "error"
    assert "is not a teammate you can delegate to" in result.result


def test_delegate_rejects_cycles_and_depth_overflow():
    cycle = _tool(
        context=_context(
            agent_id="research",
            delegation_trace=["primary", "research"],
            delegation_depth=1,
        )
    )
    result = cycle.execute({"agent_id": "primary", "task": "Send it back"})
    assert result.status == "error"
    assert "cycle rejected" in result.result

    too_deep = _tool(
        config={"max_depth": 1},
        context=_context(delegation_trace=["primary"], delegation_depth=1),
    )
    result = too_deep.execute({"agent_id": "research", "task": "Go deeper"})
    assert result.status == "error"
    assert "exceeds the maximum" in result.result


def test_delegate_enforces_message_limit():
    tool = _tool(config={"max_message_chars": 4})
    result = tool.execute({"agent_id": "research", "task": "12345"})
    assert result.status == "error"
    assert "exceeds 4 characters" in result.result


def test_delegate_reports_a_target_failure_through_the_result():
    class FailingBridge(FakeBridge):
        def agent_reply(self, query, context=None, on_event=None):
            return Reply(ReplyType.ERROR, "target exploded")

    tool = _tool(bridge=FailingBridge())

    result = tool.execute({"agent_id": "research", "task": "Do work"})

    assert result.status == "error"
    assert "target exploded" in result.result
    # Failures are shown to the watcher too, not just returned to the model.
    assert result.display is not None
    assert "Primary → Research" in result.display
    assert "target exploded" in result.display


def test_delegate_relays_the_teammates_tool_steps_as_subagent_steps():
    """The teammate's tool calls surface under this call's card, live."""

    class ToolingBridge(FakeBridge):
        def agent_reply(self, query, context=None, on_event=None):
            on_event(
                {
                    "type": "tool_execution_start",
                    "data": {"tool_name": "web_search", "arguments": {"q": "x"},
                             "tool_call_id": "t1"},
                }
            )
            on_event(
                {
                    "type": "tool_execution_end",
                    "data": {"tool_name": "web_search", "status": "success",
                             "tool_call_id": "t1", "execution_time": 0.5},
                }
            )
            # Prose must not leak into the watcher's view.
            on_event({"type": "message_update", "data": {"delta": "thinking..."}})
            return Reply(ReplyType.TEXT, "found it")

    emitted = []
    tool = _tool(bridge=ToolingBridge())
    tool.tool_call_id = "card-123"
    tool.event_callback = lambda etype, data: emitted.append((etype, data))

    result = tool.execute({"agent_id": "research", "task": "Look it up"})

    assert result.status == "success"
    steps = [data for etype, data in emitted if etype == "subagent_step"]
    assert [s["phase"] for s in steps] == ["start", "end"]
    assert all(s["card_id"] == "card-123" for s in steps)
    assert steps[0]["tool_name"] == "web_search"
    # message_update / reasoning were dropped, only tool steps relayed.
    assert all(etype == "subagent_step" for etype, _ in emitted)


def test_delegate_serializes_hands_off_to_the_same_target_session():
    """A second delegation to the same relay session waits for the first."""

    order = []
    gate = threading.Event()

    class SlowBridge(FakeBridge):
        def agent_reply(self, query, context=None, on_event=None):
            order.append(("start", query))
            gate.wait(1)
            order.append(("end", query))
            return Reply(ReplyType.TEXT, "ok")

    bridge = SlowBridge()

    def run_first():
        _tool(bridge=bridge).execute({"agent_id": "research", "task": "first"})

    first = threading.Thread(target=run_first)
    first.start()
    # Let the first delegation acquire the relay lock and start.
    deadline = time.monotonic() + 1
    while not order and time.monotonic() < deadline:
        time.sleep(0.01)

    second_done = threading.Event()

    def run_second():
        _tool(bridge=bridge).execute({"agent_id": "research", "task": "second"})
        second_done.set()

    second = threading.Thread(target=run_second)
    second.start()

    # The second must not have finished while the first still holds the lock.
    assert not second_done.wait(0.2)
    gate.set()
    first.join(2)
    second.join(2)
    assert order[0] == ("start", _query_for("first", order))
    assert order.index(("end", _query_for("first", order))) < order.index(
        ("start", _query_for("second", order))
    )


def _query_for(task, order):
    for _kind, query in order:
        if task in query:
            return query
    raise AssertionError(f"no query recorded for {task}")
