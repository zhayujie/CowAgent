"""The WeCom-app access-token refresh thread must survive a failed refresh.

``WechatComAppClient._active_refresh`` starts a single daemon thread that
re-reads the token every 60s and renews it 10 minutes before it expires. That
thread is the only thing keeping the token alive, and nothing inside its loop
catches anything: when ``fetch_access_token`` raises -- a DNS blip, a gateway
500, an invalid ``secret`` -- the exception unwinds out of ``refresh_loop`` and
the thread dies for the rest of the process lifetime. The token then expires
(WeCom hands out 2h tokens) and every later call fails until CowAgent is
restarted, with no error pointing at the real cause.
"""

import threading
import time
from unittest.mock import patch

from wechatpy.enterprise import WeChatClient

from channel.wechatcom import wechatcomapp_client as client_mod


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(0.02)
    return False


def test_refresh_loop_keeps_going_after_a_failed_fetch(monkeypatch):
    """One failed refresh must not end the loop.

    Counting passes over the refresh body is the observable proof that it
    swallowed the error and went round again. The loop waits on a stop event
    rather than ``time.sleep``, so the tick itself is what there is to count.
    """
    monkeypatch.setattr(client_mod, "TOKEN_REFRESH_CHECK_SECONDS", 0.01)
    ticks = []
    real = client_mod.WechatComAppClient._refresh_once_if_needed

    def counting(client):
        ticks.append(1)
        real(client)

    monkeypatch.setattr(client_mod.WechatComAppClient, "_refresh_once_if_needed", counting)

    with patch.object(
        WeChatClient, "fetch_access_token", side_effect=RuntimeError("network down")
    ):
        client = client_mod.WechatComAppClient("ww-test", "secret")
    try:
        assert _wait_for(lambda: len(ticks) >= 2), (
            "the refresh thread stopped after the first failed fetch; the access "
            "token will never be renewed again in this process"
        )
    finally:
        client.close()


def test_one_refresh_pass_does_not_propagate_the_error():
    """A transient failure is logged, not raised out of the refresh body."""
    with patch.object(
        WeChatClient, "fetch_access_token", side_effect=RuntimeError("network down")
    ):
        client = client_mod.WechatComAppClient("ww-test", "secret")
        client._refresh_once_if_needed()

    # Reaching this line means the exception never left the refresh body.
    assert client is not None


def test_a_healthy_pass_still_fetches_when_the_token_is_stale():
    """The happy path is unchanged: an about-to-expire token triggers a fetch."""
    with patch.object(WeChatClient, "fetch_access_token") as fetch:
        client = client_mod.WechatComAppClient("ww-test", "secret")
        # The expiry the refresher reads lives on the client, not the session.
        client.expires_at = 0
        client._refresh_once_if_needed()
    assert fetch.called
