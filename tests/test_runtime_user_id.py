# encoding:utf-8
"""RuntimeIdentity.user_id is filled from the chat sender and carried onward."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.chat_channel import ChatChannel  # noqa: E402
from common.runtime_identity import RuntimeIdentity, use_identity  # noqa: E402
from common.utils import apply_client_source  # noqa: E402


class _Msg:
    def __init__(self, actual=None, sender=None):
        self.actual_user_id = actual
        self.from_user_id = sender


class TestRuntimeUserId(unittest.TestCase):
    def test_group_sender_wins_over_the_routed_id(self):
        identity = ChatChannel._identity_for(
            None,
            {"msg": _Msg("alice", "group-bot"), "agent_id": "a", "session_id": "sess"},
        )
        self.assertEqual(identity.user_id, "alice")
        self.assertEqual(identity.session_id, "sess")

    def test_direct_message_uses_from_user_id(self):
        identity = ChatChannel._identity_for(
            None,
            {"msg": _Msg(None, "bob"), "agent_id": "a", "session_id": "sess"},
        )
        self.assertEqual(identity.user_id, "bob")

    def test_missing_sender_stays_none(self):
        identity = ChatChannel._identity_for(
            None,
            {"agent_id": "a", "session_id": "sess"},
        )
        self.assertIsNone(identity.user_id)
        self.assertEqual(identity.session_id, "sess")

    def test_header_carries_the_user_and_not_the_session(self):
        with use_identity(RuntimeIdentity(session_id="sess", user_id="alice")):
            headers = apply_client_source({})
        self.assertEqual(headers["X-Agent-User-Id"], "alice")
        self.assertNotEqual(headers["X-Agent-User-Id"], "sess")

    def test_header_omitted_when_there_is_no_user(self):
        with use_identity(RuntimeIdentity(session_id="sess")):
            headers = apply_client_source({})
        self.assertNotIn("X-Agent-User-Id", headers)


if __name__ == "__main__":
    unittest.main()
