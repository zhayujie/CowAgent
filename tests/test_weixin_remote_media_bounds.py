"""Remote media replies are bounded and guarded, like every other channel's.

A reply's ``http(s)://`` media URL comes from the model, and weixin downloads it
on the thread that is sending that reply. Two things the sibling channels
(telegram, slack, discord, dingtalk, feishu, wechatcomapp, wecom_bot) apply to
the same download were missing here:

* no cap on the whole transfer, so a server that keeps trickling bytes holds
  the send thread for as long as it likes - a socket timeout never fires while
  bytes keep arriving;
* no SSRF check, so a model-authored URL pointing at a loopback, private or
  cloud-metadata address is fetched and then uploaded to the chat.
"""

from unittest.mock import Mock, patch

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from channel.weixin import weixin_channel as wxc
from common import media_download

CHANNEL_CLS = wxc.WeixinChannel.__wrapped__


@pytest.fixture
def agent_workspace(tmp_path):
    set_agent_registry(
        AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1")
    )
    yield tmp_path
    # None, not the previous instance: an instance argument re-pins the
    # registry and would leak this workspace into the later tests.
    set_agent_registry(None)


def _response(chunks=(b"payload",), content_type="image/png"):
    resp = Mock()
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = lambda: None
    body = list(chunks)
    resp.iter_content = lambda chunk_size=None: iter(body)
    resp.close = lambda: None
    return resp


class _TricklingClock:
    """A clock that moves a minute for every byte the server hands over."""

    now = 1000.0

    @classmethod
    def monotonic(cls):
        value = cls.now
        cls.now += 60
        return value


def test_a_trickling_media_url_is_abandoned_instead_of_parking_send(
        agent_workspace, monkeypatch):
    """One byte a minute never trips a socket timeout; the transfer cap must fire."""

    def trickle(chunk_size=None):
        for _ in range(200):
            yield b"x"

    resp = _response()
    resp.iter_content = trickle
    monkeypatch.setattr(media_download, "time", _TricklingClock)

    with patch.object(wxc.requests, "get", return_value=resp) as get:
        local_path = CHANNEL_CLS._resolve_media_path("https://files.example.com/clip.mp4")

    assert get.called, "the download must have started"
    assert local_path == "", "an endless trickle must not resolve to a path"


def test_a_private_media_url_is_never_fetched_when_the_ssrf_guard_is_on(
        agent_workspace, monkeypatch):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "1")

    with patch.object(wxc.requests, "get", return_value=_response()) as get:
        local_path = CHANNEL_CLS._resolve_media_path(
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
        )

    assert local_path == ""
    assert not get.called, "the guard must reject the address before any request is made"


def test_a_public_media_url_follows_redirects_through_the_guarded_helper(
        agent_workspace, monkeypatch):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "1")
    opened = []

    def fake_safe_get(url, **kwargs):
        opened.append((url, kwargs.get("stream")))
        return _response()

    from agent.tools.utils import url_safety

    with patch.object(url_safety, "safe_get", side_effect=fake_safe_get), \
            patch.object(url_safety, "validate_url_safe"), \
            patch.object(wxc.requests, "get", side_effect=AssertionError("guard bypassed")):
        local_path = CHANNEL_CLS._resolve_media_path("https://files.example.com/pic.png")

    assert opened == [("https://files.example.com/pic.png", True)]
    assert local_path, "a public URL must still download"


def test_the_plain_download_stays_when_the_guard_is_off(agent_workspace, monkeypatch):
    """The default (guard off) must keep the old behaviour, DNS lookups included."""
    from agent.tools.utils import url_safety

    monkeypatch.setattr(url_safety, "_ssrf_protection_enabled", lambda: False)

    with patch.object(url_safety, "safe_get", side_effect=AssertionError("guard used")), \
            patch.object(wxc.requests, "get", return_value=_response()) as get:
        local_path = CHANNEL_CLS._resolve_media_path("http://127.0.0.1:8080/private.png")

    assert get.called
    assert local_path, "with the guard off nothing about the download changes"
