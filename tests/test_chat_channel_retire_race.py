# encoding:utf-8
"""
A message that arrives while the consumer retires its session must not be lost.

ChatChannel._consume_session checks ``context_queue.empty()`` without holding
``self.lock``, then takes the lock and deletes the session. produce() files a
new message into the existing queue under that lock. When produce() runs in
the gap between the check and the delete, the message goes into a queue that
is then dropped from ``self.sessions``: nothing ever dispatches it and the user
gets no reply.

The tests drive that interleaving deterministically by running produce() from
inside the consumer's ``empty()`` call.
"""
import os
import sys
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import Context, ContextType  # noqa: E402
from common.dequeue import Dequeue  # noqa: E402

SESSION = "s1"


def _make_channel():
    """A ChatChannel without the consume thread that the real __init__ starts."""
    from channel.chat_channel import ChatChannel

    ch = ChatChannel.__new__(ChatChannel)
    ch.lock = threading.Lock()
    ch.sessions = {}
    ch.futures = {}
    ch.prepare_project_context = lambda context: None
    return ch


def _agent_bridge():
    bridge = MagicMock()
    bridge.route_context.return_value = None
    bridge._cancel_key.side_effect = lambda agent_id, session_id, default: session_id
    return bridge


def _message(text="hello"):
    return Context(ContextType.TEXT, text, {"session_id": SESSION})


def _idle_session(ch):
    """A session whose last turn finished: empty queue, free slot."""
    queue = Dequeue()
    ch.sessions[SESSION] = [queue, threading.BoundedSemaphore(1)]
    return queue


def _produce_during_empty_check(ch, queue, context):
    """Make the consumer's empty() check let produce() run right after it."""
    original_empty = queue.empty

    def empty_then_produce():
        result = original_empty()
        if result:
            # The consumer holds no lock here, so a channel thread can file a
            # new message. Run it on its own thread, as a channel would.
            producer = threading.Thread(target=ch.produce, args=(context,))
            producer.start()
            producer.join(timeout=5)
            assert not producer.is_alive()
        return result

    queue.empty = empty_then_produce


def test_message_produced_during_retire_is_kept():
    ch = _make_channel()
    queue = _idle_session(ch)
    context = _message()
    _produce_during_empty_check(ch, queue, context)

    with patch("bridge.bridge.Bridge") as bridge_cls:
        bridge_cls.return_value.get_agent_bridge.return_value = _agent_bridge()
        ch._consume_session(SESSION)

    assert SESSION in ch.sessions, "session was retired with a message still queued"
    assert ch.sessions[SESSION][0].qsize() == 1


def test_message_produced_during_retire_is_dispatched_next_tick():
    ch = _make_channel()
    queue = _idle_session(ch)
    context = _message()
    _produce_during_empty_check(ch, queue, context)

    with patch("bridge.bridge.Bridge") as bridge_cls, \
            patch("channel.chat_channel.handler_pool") as pool:
        bridge_cls.return_value.get_agent_bridge.return_value = _agent_bridge()
        ch._consume_session(SESSION)
        del queue.empty  # back to the real check
        if SESSION in ch.sessions:
            ch._consume_session(SESSION)

    pool.submit.assert_called_once_with(ch._handle, context)


def test_idle_session_is_still_retired():
    ch = _make_channel()
    _idle_session(ch)

    ch._consume_session(SESSION)

    assert SESSION not in ch.sessions
    assert SESSION not in ch.futures
