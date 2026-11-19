"""The WeCom app client must not ask the token endpoint on every tick.

The background refresher was written to renew the token when it is close to
expiring, but it looked the expiry up in the session under
``<corp_id>_expires_at`` -- a key wechatpy never writes. It keeps the expiry on
the client (``expires_at``, set by ``_fetch_access_token``) and stores only the
token in the session, so every check read 0, decided the token was expiring, and
fetched a new one. At one check per minute that is ~1440 gettoken calls a day
against a rate-limited endpoint, instead of the ~12 a valid 2h token needs.

The refresher also had no stop path: each restarted channel left one more
poller behind, multiplying the calls.
"""
import threading
import time

import pytest
from wechatpy.client.base import BaseWeChatClient

from channel.wechatcom import wechatcomapp_client as client_module
from channel.wechatcom.wechatcomapp_client import WechatComAppClient

THREAD_NAME = "wechatcom_token_refresh_thread"


@pytest.fixture
def fetches(monkeypatch):
    """Count token fetches and answer them like the SDK does, without network."""
    calls = []

    def fetch(self, url, params):
        calls.append(url)
        token = f"token-{len(calls)}"
        self.session.set(self.access_token_key, token, 7200)
        self.expires_at = time.time() + 7200
        return {"access_token": token, "expires_in": 7200}

    monkeypatch.setattr(BaseWeChatClient, "_fetch_access_token", fetch)
    return calls


@pytest.fixture
def client(fetches):
    created = WechatComAppClient("corp", "secret0123456789")
    try:
        yield created
    finally:
        # The unfixed client has no close(); do not let teardown hide that.
        getattr(created, "close", lambda: None)()


def test_a_fresh_token_is_not_fetched_again(client, fetches):
    assert len(fetches) == 1, "the client should hold a token after construction"

    for _ in range(3):
        client._refresh_once_if_needed()

    assert len(fetches) == 1, "a token that is valid for another 2h was fetched again"


def test_a_token_about_to_lapse_is_fetched_again(client, fetches):
    """Control: renewing is still what happens when renewal is due."""
    client.expires_at = time.time() + 60

    client._refresh_once_if_needed()

    assert len(fetches) == 2


def test_close_stops_the_refresh_thread(monkeypatch, fetches):
    monkeypatch.setattr(client_module, "TOKEN_REFRESH_CHECK_SECONDS", 0.02)
    created = WechatComAppClient("corp", "secret0123456789")
    try:
        created.close()
        deadline = time.time() + 5
        while time.time() < deadline:
            if not any(t.name == THREAD_NAME and t.is_alive() for t in threading.enumerate()):
                break
            time.sleep(0.02)
        assert not any(t.name == THREAD_NAME and t.is_alive() for t in threading.enumerate()), (
            "the refresh thread outlived close()"
        )
    finally:
        getattr(created, "close", lambda: None)()
