# encoding:utf-8
"""
Regression tests for the scheduler's skill_call delivery path.

`_execute_skill_call` re-wrapped every agent reply as TEXT using only
``reply.content``. When the agent ends its turn by sending files, agent_reply
returns a FILE / IMAGE_URL reply whose ``content`` is the media URL while the
prose rides in ``text_content`` (``bridge/agent_bridge.py::_create_file_reply``).
The scheduled task then delivered a bare local path: the file never reached the
user and the agent's answer was dropped. ``_execute_agent_task``, the sibling
path in the same module, already forwards such a reply untouched.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import Reply, ReplyType
from agent.tools.scheduler import integration

FILE_URL = "file:///workspace/reports/daily.pdf"
PROSE = "12 alerts, 3 pending."


def _file_reply():
    reply = Reply(ReplyType.FILE, FILE_URL)
    reply.file_type = "document"
    reply.file_name = "daily.pdf"
    reply.text_content = PROSE
    return reply


class _Bridge:
    def __init__(self, reply):
        self._reply = reply

    def agent_reply(self, query, context=None, on_event=None, clear_history=False):
        return self._reply


class _Channel:
    def __init__(self):
        self.sent = []
        self.request_to_session = {}

    def send(self, reply, context):
        self.sent.append(reply)


class TestSchedulerSkillCallFileReply(unittest.TestCase):
    """A skill that produces files must deliver them, not a bare path."""

    def _run(self, reply, **action):
        channel = _Channel()
        task = {
            "id": "task-1",
            "action": {
                "type": "skill_call",
                "call_name": "daily_report",
                "receiver": "user-1",
                "channel_type": "web",
                **action,
            },
        }
        with patch.object(integration, "_resolve_delivery_channel", return_value=channel), \
                patch.object(integration, "_remember_delivered_output", lambda *a, **k: None):
            ok = integration._execute_skill_call(task, _Bridge(reply), "agent-1")
        return ok, channel

    def test_a_file_reply_reaches_the_channel_intact(self):
        ok, channel = self._run(_file_reply())

        self.assertTrue(ok)
        self.assertEqual(len(channel.sent), 1)
        delivered = channel.sent[0]
        self.assertEqual(delivered.type, ReplyType.FILE)
        self.assertEqual(delivered.content, FILE_URL)
        self.assertEqual(delivered.text_content, PROSE)
        self.assertEqual(delivered.file_name, "daily.pdf")

    def test_extra_files_ride_along_untouched(self):
        reply = _file_reply()
        extra = Reply(ReplyType.FILE, "file:///workspace/reports/appendix.pdf")
        reply.extra_replies = [extra]

        _, channel = self._run(reply)

        self.assertEqual(len(channel.sent[0].extra_replies), 1)
        self.assertEqual(channel.sent[0].extra_replies[0].content, extra.content)

    def test_result_prefix_lands_on_the_accompanying_text(self):
        _, channel = self._run(_file_reply(), result_prefix="Daily report")

        delivered = channel.sent[0]
        self.assertEqual(delivered.type, ReplyType.FILE)
        self.assertEqual(delivered.content, FILE_URL)
        self.assertEqual(delivered.text_content, "Daily report\n\n" + PROSE)

    def test_a_text_reply_is_still_wrapped_as_text(self):
        _, channel = self._run(Reply(ReplyType.TEXT, "nothing to report"))

        delivered = channel.sent[0]
        self.assertEqual(delivered.type, ReplyType.TEXT)
        self.assertEqual(delivered.content, "nothing to report")

    def test_text_reply_prefix_is_unchanged(self):
        _, channel = self._run(Reply(ReplyType.TEXT, "all clear"), result_prefix="Health check")

        self.assertEqual(channel.sent[0].content, "Health check\n\nall clear")


if __name__ == "__main__":
    unittest.main()
