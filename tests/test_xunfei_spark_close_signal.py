"""The Xunfei Spark reader must be woken by a usable end marker.

The socket thread talks to ``reply()`` through a module-level queue. When the
connection drops before the final chunk, ``on_close`` is the only thing that
can release the reader, so what it puts on the queue has to be something the
reader can actually inspect. It used to put the bare string ``"END"``, which
made ``data_item.is_end`` raise ``AttributeError``; ``reply()`` swallows every
exception in that loop, so the request simply spun out its entire budget and
left its queue behind.
"""

import queue
import time
from types import SimpleNamespace

import pytest

from models.xunfei import xunfei_spark_bot as xsb


@pytest.fixture(autouse=True)
def _isolate_module_maps():
    """``queue_map``/``reply_map`` are module state; never let a case leak."""
    xsb.queue_map.clear()
    xsb.reply_map.clear()
    yield
    xsb.queue_map.clear()
    xsb.reply_map.clear()


@pytest.fixture
def bot(monkeypatch):
    instance = xsb.XunFeiBot()
    monkeypatch.setattr(
        instance.sessions, "session_query",
        lambda query, session_id: SimpleNamespace(messages=[]),
    )
    recorded = []
    monkeypatch.setattr(
        instance.sessions, "session_reply",
        lambda content, session_id, tokens=None: recorded.append((content, tokens)),
    )
    instance.recorded = recorded
    return instance


class _Context:
    """The bits of bridge.context.Context that reply() touches."""

    def __init__(self, session_id):
        self.type = xsb.ContextType.TEXT
        self._session_id = session_id

    def __getitem__(self, key):
        return self._session_id


def _drop_after_one_chunk(monkeypatch, text="半截回复"):
    """A socket that delivers one chunk and then closes, like a real drop."""

    def _create(self, prompt, session_id, temperature=0.5):
        pending = queue.Queue(1000)
        xsb.queue_map[session_id] = pending
        pending.put(xsb.ReplyItem(text))
        xsb.on_close(SimpleNamespace(session_id=session_id), None, None)

    monkeypatch.setattr(xsb.XunFeiBot, "create_web_socket", _create)


def test_close_hands_the_reader_a_reply_item():
    pending = queue.Queue(10)
    xsb.queue_map["spark-close"] = pending

    xsb.on_close(SimpleNamespace(session_id="spark-close"), None, None)

    item = pending.get_nowait()
    assert item.is_end is True
    assert item.reply == ""


def test_close_after_the_reader_finished_does_not_raise():
    # The reader releases the queue before the socket thread always closes, so
    # on_close regularly runs with nothing left to signal.
    xsb.on_close(SimpleNamespace(session_id="spark-gone"), None, None)


def test_a_dropped_socket_does_not_burn_the_whole_budget(bot, monkeypatch):
    _drop_after_one_chunk(monkeypatch)

    started = time.monotonic()
    reply = bot.reply("hi", _Context("spark-drop"))
    elapsed = time.monotonic() - started

    assert reply.content == "半截回复"
    # Unfixed, the reader had to exhaust its 300 iterations of queue.get(0.1).
    assert elapsed < 2.0
    assert bot.recorded == [("半截回复", None)]


def test_the_queues_are_released_when_the_reply_step_fails(bot, monkeypatch):
    _drop_after_one_chunk(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("session store unavailable")

    monkeypatch.setattr(bot.sessions, "session_reply", _boom)

    with pytest.raises(RuntimeError):
        bot.reply("hi", _Context("spark-boom"))

    assert xsb.queue_map == {}
    assert xsb.reply_map == {}
