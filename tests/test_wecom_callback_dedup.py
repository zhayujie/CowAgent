"""Concurrent webhook redeliveries must enqueue only one turn."""

import threading

import pytest


@pytest.fixture
def callback_channel(monkeypatch):
    import channel.file_cache as cache_module
    from channel.channel import Channel
    from channel.wecom_bot import wecom_bot_channel as module
    from common.expired_dict import ExpiredDict

    cls = module.WecomBotChannel.__wrapped__
    channel = cls.__new__(cls)
    Channel.__init__(channel)
    channel.channel_type = "wecom_bot"
    channel.received_msgs = ExpiredDict(3600)
    channel._callback_streams = ExpiredDict(600)
    channel._callback_lock = threading.Lock()
    queued = []
    channel.produce = queued.append
    monkeypatch.setattr(module, "conf", lambda: {"image_create_prefix": []})
    cache = cache_module.FileCache()
    monkeypatch.setattr(cache_module, "get_file_cache", lambda: cache)
    return channel, queued


def message(identifier):
    return {
        "msgid": identifier, "msgtype": "text", "chattype": "single",
        "from": {"userid": "fixture-user"},
        "text": {"content": "fixture question"},
    }


def test_concurrent_repeated_callback_queues_only_one_turn(callback_channel, monkeypatch):
    channel, queued = callback_channel
    original_get = channel.received_msgs.get
    first_read = threading.Event()
    another_read = threading.Event()
    release = threading.Event()
    read_lock = threading.Lock()
    reads = 0
    errors = []
    replies = []

    def controlled_get(identifier):
        nonlocal reads
        value = original_get(identifier)
        with read_lock:
            reads += 1
            number = reads
        if number == 1:
            first_read.set()
            if not release.wait(3):
                raise AssertionError("first callback was not released")
        else:
            another_read.set()
        return value

    monkeypatch.setattr(channel.received_msgs, "get", controlled_get)

    def receive():
        try:
            replies.append(channel._callback_handle_message(message("same-message")))
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=receive)
    second = threading.Thread(target=receive)
    try:
        first.start()
        assert first_read.wait(3)
        second.start()
        another_read.wait(0.2)
    finally:
        release.set()
        for thread in (first, second):
            if thread.ident is not None:
                thread.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert len(queued) == 1
    assert sum(reply is None for reply in replies) == 1
    assert queued[0].content == "fixture question"
    assert len(channel._callback_streams) == 1


def test_sequential_repeated_callback_remains_filtered(callback_channel):
    channel, queued = callback_channel
    first = channel._callback_handle_message(message("same-message"))
    assert first["msgtype"] == "stream"
    assert channel._callback_handle_message(message("same-message")) is None
    assert len(queued) == 1


def test_distinct_callback_ids_each_queue_a_turn(callback_channel):
    channel, queued = callback_channel
    assert channel._callback_handle_message(message("first"))["msgtype"] == "stream"
    assert channel._callback_handle_message(message("second"))["msgtype"] == "stream"
    assert len(queued) == 2


def test_missing_callback_id_does_not_filter_later_messages(callback_channel):
    channel, queued = callback_channel
    assert channel._callback_handle_message(message(""))["msgtype"] == "stream"
    assert channel._callback_handle_message(message(""))["msgtype"] == "stream"
    assert len(queued) == 2


# ---------------------------------------------------------------------------
# the long-connection path feeds the same dedupe table
# ---------------------------------------------------------------------------


def _long_connection(body):
    """A `aibot_msg_callback` frame: the message sits under `body`."""
    return {"body": body, "headers": {"req_id": ""}}


def test_long_connection_repeated_msgid_queues_only_one_turn(callback_channel):
    channel, queued = callback_channel
    channel._handle_msg_callback(_long_connection(message("same-message")))
    channel._handle_msg_callback(_long_connection(message("same-message")))

    assert len(queued) == 1


def test_long_connection_missing_msgid_does_not_filter_later_messages(callback_channel):
    """A payload without msgid must not poison the table for every later one."""
    channel, queued = callback_channel
    channel._handle_msg_callback(_long_connection(message("")))
    channel._handle_msg_callback(_long_connection(message("")))

    assert len(queued) == 2


def test_long_connection_distinct_msgids_each_queue_a_turn(callback_channel):
    channel, queued = callback_channel
    channel._handle_msg_callback(_long_connection(message("first")))
    channel._handle_msg_callback(_long_connection(message("second")))

    assert len(queued) == 2
