"""The Feishu Markdown image downloader must use the same public-IP rule as the
shared SSRF guard.

``validate_public_image_url`` is the *only* unconditional SSRF check on this
path: tool-side guards are opt-in (``web_security_ssrf_protection`` defaults to
False), while every image URL here comes from the model's Markdown reply. The
channel used to keep its own six-flag copy of the rule, which missed the
100.64.0.0/10 shared address space (Alibaba Cloud's 100.100.100.200 metadata
endpoint) -- ``is_private`` is False there, only ``is_global`` catches it.

The regression cases below drive the real functions and assert on observable
behaviour (a ValueError, and whether an HTTP GET was issued at all), not on
which private helper got called.
"""

import socket

import pytest

from agent.tools.utils import url_safety
from channel.feishu import feishu_static_card as card


# Addresses that are NOT private/loopback/link-local/reserved/multicast/
# unspecified but are NOT globally routable either.
SHARED_ADDRESSES = ["100.100.100.200", "100.64.0.1"]

# Addresses the old six-flag copy already rejected. Kept as controls so the
# change cannot be read as "weakening the guard".
ALREADY_BLOCKED = ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1"]

PUBLIC_ADDRESSES = ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"]


def _url(ip):
    host = f"[{ip}]" if ":" in ip else ip
    return f"http://{host}/latest/meta-data/x.png"


class _Response:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "image/png"}
        self._chunks = chunks if chunks is not None else [b"png"]
        self.closed = False

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def close(self):
        self.closed = True


@pytest.mark.parametrize("ip", SHARED_ADDRESSES)
def test_shared_address_space_is_rejected_before_any_request(ip):
    with pytest.raises(ValueError, match="non-public"):
        card.validate_public_image_url(_url(ip))


@pytest.mark.parametrize("ip", SHARED_ADDRESSES)
def test_download_never_issues_a_get_to_a_shared_address(ip, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Response()

    with pytest.raises(ValueError, match="non-public"):
        card.download_public_image(_url(ip), get=fake_get)

    assert calls == [], "an SSRF target must be refused before the socket opens"


@pytest.mark.parametrize("ip", SHARED_ADDRESSES)
def test_dns_name_resolving_into_shared_address_space_is_rejected(ip, monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="non-public"):
        card.validate_public_image_url("https://cdn.example.com/image.png")


@pytest.mark.parametrize("ip", SHARED_ADDRESSES)
def test_redirect_into_shared_address_space_is_rejected(ip, monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    calls = []
    redirect = _Response(
        status_code=302, headers={"Location": _url(ip)}
    )

    def fake_get(url, **kwargs):
        calls.append(url)
        return redirect

    with pytest.raises(ValueError, match="non-public"):
        card.download_public_image("https://cdn.example.com/image.png", get=fake_get)

    assert len(calls) == 1, "the second hop must be refused, not fetched"
    assert redirect.closed is True


def test_guard_stays_unconditional_when_the_global_switch_is_off(monkeypatch):
    # The instance-wide SSRF switch is opt-in and off by default. The channel
    # check must not depend on it, because these URLs come from the model.
    monkeypatch.delenv("WEB_SECURITY_SSRF_PROTECTION", raising=False)
    import config
    monkeypatch.setattr(config, "conf", lambda: {})
    assert url_safety._ssrf_protection_enabled() is False

    with pytest.raises(ValueError, match="non-public"):
        card.validate_public_image_url(_url("100.100.100.200"))


def test_channel_matches_the_shared_rule_for_every_address_class():
    """Guard against the two rule copies drifting apart again: derive the
    expected verdict from the shared guard instead of hard-coding a list."""
    for ip in SHARED_ADDRESSES + ALREADY_BLOCKED + PUBLIC_ADDRESSES:
        expected_blocked = url_safety._is_blocked_ip(socket_ip(ip))
        try:
            card.validate_public_image_url(_url(ip))
            blocked = False
        except ValueError:
            blocked = True
        assert blocked == expected_blocked, f"verdict for {ip} diverged from url_safety"


def socket_ip(value):
    import ipaddress
    return ipaddress.ip_address(value)


@pytest.mark.parametrize("ip", ALREADY_BLOCKED)
def test_previously_blocked_addresses_stay_blocked(ip):
    with pytest.raises(ValueError, match="non-public"):
        card.validate_public_image_url(_url(ip))


@pytest.mark.parametrize("ip", PUBLIC_ADDRESSES)
def test_public_addresses_are_still_accepted(ip, monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    card.validate_public_image_url("https://cdn.example.com/image.png")
    card.validate_public_image_url(_url(ip))


def test_unsupported_scheme_and_missing_host_are_still_rejected():
    with pytest.raises(ValueError):
        card.validate_public_image_url("ftp://example.com/image.png")
    with pytest.raises(ValueError):
        card.validate_public_image_url("http:///image.png")


def test_public_image_download_still_works(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    calls = []
    response = _Response(chunks=[b"\x89PNG"])

    def fake_get(url, **kwargs):
        calls.append(url)
        return response

    payload, content_type = card.download_public_image(
        "https://cdn.example.com/chart.png", get=fake_get
    )
    assert payload == b"\x89PNG" and content_type == "image/png"
    assert calls == ["https://cdn.example.com/chart.png"]
    assert response.closed is True
