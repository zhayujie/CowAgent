"""A refused Weixin text bubble must reach the caller as a failure.

``send()`` raises when the context_token is missing because "a scheduled push
routes through this same send(), and the scheduler treats a silent return as
delivered and deletes a one-time task". The platform rejecting the bubble with
HTTP 200 + a non-zero ``ret``/``errcode`` (send window closed, quota used up) is
the same outcome, and a read timeout on the second chunk of a long answer is
worse: the tail was never attempted.
"""

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel.weixin import weixin_channel as module  # noqa: E402


def _channel(send_results):
    """A Weixin channel whose send-API answers with *send_results* in order."""
    cls = module.WeixinChannel.__wrapped__
    channel = cls.__new__(cls)
    channel._context_tokens = {"user-1": "context-token"}
    channel._context_tokens_lock = threading.Lock()
    channel.api = MagicMock()
    channel.api.send_text.side_effect = list(send_results)
    return channel


def _long_text():
    """A body long enough to need three chunks, with no split-friendly breaks."""
    text = "x" * (module.TEXT_CHUNK_LIMIT * 2 + 100)
    chunks = module.WeixinChannel.__wrapped__._split_text(text, module.TEXT_CHUNK_LIMIT)
    assert len(chunks) == 3
    return text


def test_a_closed_send_window_is_not_reported_as_delivered():
    channel = _channel([{"ret": 0, "errcode": 45009, "errmsg": "quota"}])

    with patch.object(module, "time", MagicMock()):
        with pytest.raises(RuntimeError, match="rejected"):
            channel._send_text("hello", "user-1", "context-token")

    assert channel._context_tokens["user-1"] == "context-token", (
        "a quota rejection says nothing about the cached context_token"
    )


def test_an_expired_session_raises_and_drops_the_token():
    channel = _channel([{"ret": -14, "errcode": -14}])

    with patch.object(module, "time", MagicMock()):
        with pytest.raises(RuntimeError, match="rejected"):
            channel._send_text("hello", "user-1", "context-token")

    assert "user-1" not in channel._context_tokens


def test_a_failed_middle_chunk_does_not_swallow_the_tail():
    text = _long_text()
    channel = _channel([
        {"ret": 0},
        requests.exceptions.ReadTimeout("Read timed out."),
        {"ret": 0},
    ])

    with patch.object(module, "time", MagicMock()):
        channel._send_text(text, "user-1", "context-token")

    assert channel.api.send_text.call_count == 3, (
        "the chunks after a rejected one must still be attempted"
    )


def test_a_partial_delivery_does_not_raise_into_a_full_resend():
    # ChatChannel._send retries a raising send() from the first chunk, which
    # would deliver the chunks that already went out a second and third time.
    channel = _channel([{"ret": 0}, {"ret": 0, "errcode": 45009}, {"ret": 0}])

    with patch.object(module, "time", MagicMock()):
        channel._send_text(_long_text(), "user-1", "context-token")

    assert channel.api.send_text.call_count == 3


def test_every_chunk_rejected_raises():
    channel = _channel([
        {"ret": 0, "errcode": 45009},
        requests.exceptions.ReadTimeout("Read timed out."),
        {"ret": -14, "errcode": -14},
    ])

    with patch.object(module, "time", MagicMock()):
        with pytest.raises(RuntimeError, match="3/3"):
            channel._send_text(_long_text(), "user-1", "context-token")


def test_a_fully_delivered_answer_stays_silent():
    channel = _channel([{"ret": 0}, {"ret": 0}, {"ret": 0}])

    with patch.object(module, "time", MagicMock()):
        channel._send_text(_long_text(), "user-1", "context-token")

    assert channel.api.send_text.call_count == 3


def test_a_response_without_ret_or_errcode_counts_as_delivered():
    channel = _channel([{"msgid": "m1"}])

    with patch.object(module, "time", MagicMock()):
        channel._send_text("hello", "user-1", "context-token")

    assert channel.api.send_text.call_count == 1
