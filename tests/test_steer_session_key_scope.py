"""A steer instruction must reach the run it was aimed at.

Session ids are only unique within one Agent, so the cancel and steer
registries are keyed by a scoped id (``AgentBridge.scoped_session_key``, i.e.
``"{agent_id}::{session_id}"`` for any non-default Agent). Every submit-side
caller already namespaces: ``AgentBridge.steer_session``, the web sessions API
(``sessions.py:417``) and ``cloud_client.py:1538``.

``agent_reply`` registered its steer inbox under the **raw** session id, while
the cancel token right next to it was already scoped. The two halves therefore
disagreed about the key:

* a steer aimed at a non-default Agent looked up ``"agent-a::s1"``, found an
  empty bucket and came back ``INACTIVE`` -- the Agent ignored it;
* when the default Agent had a run under the same bare id, the bucket held two
  inboxes and ``submit`` returned ``AMBIGUOUS``, so neither run received it --
  and with a single inbox the instruction landed in the wrong Agent's run.
"""

import unittest
from unittest.mock import patch

from agent.protocol.steer import SteerRegistry, SteerStatus
from bridge.agent_bridge import AgentBridge


class _AgentEntry:
    def __init__(self, agent_id):
        self.id = agent_id
        self.name = agent_id


class _AgentRegistry:
    def __init__(self, default_agent_id="default"):
        self.default_agent_id = default_agent_id

    def get(self, agent_id=None, require_enabled=False):
        return _AgentEntry(agent_id or self.default_agent_id)

    def list(self):
        return [self.get(self.default_agent_id)]


def _bridge(default_agent_id="default"):
    bridge = AgentBridge.__new__(AgentBridge)
    bridge.agent_registry = _AgentRegistry(default_agent_id)
    return bridge


class SteerKeyScopeTest(unittest.TestCase):
    """The key agent_reply registers under must be the key submit looks up."""

    def test_the_two_sides_agree_for_a_non_default_agent(self):
        bridge = _bridge()
        session_id = "s1"

        register_key = bridge.scoped_session_key(session_id, "agent-a")
        submit_key = bridge.scoped_session_key(session_id, "agent-a")

        self.assertEqual(
            register_key, submit_key,
            "agent_reply and steer_session must compute the same key",
        )
        self.assertNotEqual(
            register_key, session_id,
            "a non-default Agent's key must be namespaced, otherwise two Agents "
            "sharing a session id steer each other",
        )

    def test_a_scoped_register_is_reachable_by_submit(self):
        bridge = _bridge()
        registry = SteerRegistry()
        key = bridge.scoped_session_key("s1", "agent-a")
        registry.register(key)

        result = registry.submit(bridge.scoped_session_key("s1", "agent-a"), "go")

        self.assertIs(result.status, SteerStatus.ACCEPTED)

    def test_a_bare_register_is_not_reachable_from_a_scoped_submit(self):
        # What agent_reply used to do: register under the raw session id.
        registry = SteerRegistry()
        registry.register("s1")

        result = registry.submit(_bridge().scoped_session_key("s1", "agent-a"), "go")

        self.assertIs(result.status, SteerStatus.INACTIVE)

    def test_two_agents_sharing_a_session_id_do_not_collide(self):
        # The default Agent keeps the bare key, a second Agent gets its own
        # bucket, so each run receives only what was aimed at it.
        registry = SteerRegistry()
        default_key = _bridge().scoped_session_key("s1", None)
        other_key = _bridge().scoped_session_key("s1", "agent-a")

        registry.register(default_key)
        registry.register(other_key)

        self.assertIs(
            registry.submit(other_key, "for agent-a").status, SteerStatus.ACCEPTED
        )
        self.assertIs(
            registry.submit(default_key, "for default").status, SteerStatus.ACCEPTED
        )

    def test_the_default_agent_keeps_the_bare_key(self):
        # Legacy shape on purpose: existing installs key the default Agent by
        # the raw session id, and the web/API submit paths rely on it.
        bridge = _bridge()
        self.assertEqual(bridge.scoped_session_key("s1", None), "s1")
        self.assertEqual(bridge.scoped_session_key("s1", "default"), "s1")

    def test_agent_reply_scopes_the_steer_registration(self):
        # Drive the real registration site rather than re-deriving the key.
        bridge = _bridge()
        registry = SteerRegistry()
        seen = {}

        class _Agent:
            permission_mode = None
            tools = []
            captured_actions = []
            memory_manager = None
            skill_manager = None
            runtime_info = None
            workspace_dir = None
            max_steps = 8

            def run_stream(self, *args, **kwargs):
                # Capture the key the run was registered under, then finish.
                seen["key"] = registry.submit(
                    bridge.scoped_session_key("s1", "agent-a"), "mid-run steer"
                ).status
                return "done"

        from bridge.context import Context

        context = Context()
        context["session_id"] = "s1"
        context["agent_id"] = "agent-a"

        with patch.object(AgentBridge, "_has_runtime", return_value=True), \
             patch.object(AgentBridge, "get_agent", return_value=_Agent()), \
             patch.object(AgentBridge, "route_context", return_value="agent-a"), \
             patch.object(AgentBridge, "_seed_team_members", return_value=None), \
             patch.object(AgentBridge, "_peer_speaker", return_value=None), \
             patch("bridge.agent_bridge.get_steer_registry", return_value=registry), \
             patch("bridge.agent_bridge.get_cancel_registry"), \
             patch("agent.evolution.trigger.mark_run_active", create=True):
            bridge.agent_reply("hello", context)

        self.assertEqual(
            seen.get("key"), SteerStatus.ACCEPTED,
            "a mid-run steer aimed at a non-default Agent never reached it",
        )


if __name__ == "__main__":
    unittest.main()