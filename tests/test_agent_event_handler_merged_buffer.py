"""The weixin thinking buffer must not survive the end of a tool-calling turn.

``AgentEventHandler`` caps instant thinking messages on weixin at
``WEIXIN_THINKING_INSTANT_MAX``; past that, ``_send_to_channel`` stops sending
and parks the text in ``_merged_buf``, which is drained by the next non-tool
turn or by ``agent_end``.

The drain used to sit in the *non-tool* branch of ``_handle_message_end`` only.
The tool-calling branch sent its own text and returned without draining, so
every turn beyond the cap left its line parked: the channel silently withheld
the text for the rest of the run, and a run that stopped on a tool-calling turn
dropped it with nothing in the log. These tests pin the drain to both paths, and
pin the under-cap behaviour -- one message per turn, no buffering -- so the fix
cannot be "widen the cap" or "buffer everything".
"""

from bridge.agent_event_handler import WEIXIN_THINKING_INSTANT_MAX, AgentEventHandler
from bridge.context import Context, ContextType
from common import const


class _RecordingChannel:
    """Stands in for the channel: records what ``_do_send`` would have sent."""

    def __init__(self):
        self.sent = []

    def _send(self, reply, context):
        self.sent.append(reply.content)


def _weixin_handler():
    channel = _RecordingChannel()
    context = Context(ContextType.TEXT, "hello", {
        "channel": channel,
        "channel_type": const.WEIXIN,
    })
    handler = AgentEventHandler(context=context, original_callback=None)
    return handler, channel.sent


def _run_tool_turn(handler, turn):
    """One turn that streams text and then calls a tool, as agent_stream emits it."""
    handler.handle_event({"type": "turn_start", "data": {"turn": turn}})
    handler.handle_event({"type": "message_update", "data": {"delta": f"t{turn}"}})
    handler.handle_event({"type": "message_end", "data": {
        "content": f"t{turn}",
        "tool_calls": [{"id": f"call_{turn}", "name": "read_file", "arguments": {}}],
        "stop_reason": "tool_use",
    }})


def test_a_tool_calling_turn_past_the_cap_drains_what_it_buffered():
    """The regression: a tool turn must not end with text still parked.

    No ``agent_end`` is emitted, which is the point -- a run that stops on a
    tool-calling turn is the shape that lost the text outright.
    """
    handler, sent = _weixin_handler()
    turns = WEIXIN_THINKING_INSTANT_MAX + 2

    for turn in range(1, turns + 1):
        _run_tool_turn(handler, turn)

    assert handler._merged_buf == [], "text was withheld past the cap with nothing to drain it"
    assert sent == [f"t{turn}" for turn in range(1, turns + 1)], "buffered turns must reach the channel"


def test_a_final_reply_does_not_resend_what_a_tool_turn_already_drained():
    """The drain belongs to the tool turn; the final turn must not repeat it."""
    handler, sent = _weixin_handler()
    for turn in range(1, WEIXIN_THINKING_INSTANT_MAX + 3):
        _run_tool_turn(handler, turn)
    after_tool_turns = list(sent)

    handler.handle_event({"type": "turn_start", "data": {"turn": 99}})
    handler.handle_event({"type": "message_update", "data": {"delta": "done"}})
    handler.handle_event({"type": "message_end", "data": {"content": "done", "tool_calls": []}})

    assert handler._merged_buf == []
    assert sent == after_tool_turns, "the final reply must not duplicate an already-drained turn"


def test_turns_under_the_cap_are_still_sent_one_by_one():
    """Below the cap nothing may be buffered or merged -- batching stays opt-in."""
    handler, sent = _weixin_handler()
    turns = WEIXIN_THINKING_INSTANT_MAX - 4

    for turn in range(1, turns + 1):
        _run_tool_turn(handler, turn)

    assert handler._merged_buf == [], "under the cap the buffer must stay empty"
    assert sent == [f"t{turn}" for turn in range(1, turns + 1)], "each turn is its own message"


def test_a_non_weixin_channel_is_never_buffered():
    """The drain is weixin-only; another channel must be unaffected by the fix."""
    channel = _RecordingChannel()
    context = Context(ContextType.TEXT, "hello", {
        "channel": channel,
        "channel_type": const.OPENAI,
    })
    handler = AgentEventHandler(context=context, original_callback=None)
    turns = WEIXIN_THINKING_INSTANT_MAX + 2

    for turn in range(1, turns + 1):
        _run_tool_turn(handler, turn)

    assert handler._merged_buf == []
    assert channel.sent == [f"t{turn}" for turn in range(1, turns + 1)]
