"""QR login uses ``weixin_proxy`` when set and goes direct if it fails."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel.weixin import weixin_api

PROXY = "http://proxy.invalid:18080"


@pytest.fixture(autouse=True)
def _reset_cooldown():
    weixin_api._login_proxy_down_until.clear()
    yield
    weixin_api._login_proxy_down_until.clear()


def _ok(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def _run(call, proxy, outcomes, now=1000.0):
    """Run *call* with ``weixin_proxy`` set to *proxy*; each request consumes the
    next item of *outcomes* (an exception is raised, anything else returned).
    Returns ``(result, calls)`` where each call records whether it was proxied."""
    calls = []
    pending = list(outcomes)

    def fake_request(method, url, **kwargs):
        calls.append("proxy" if kwargs.get("proxies") else "direct")
        outcome = pending.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    fake_time = MagicMock()
    fake_time.time.return_value = now
    with patch("config.conf", return_value={"weixin_proxy": proxy}), \
            patch.object(weixin_api.requests, "request", side_effect=fake_request), \
            patch.object(weixin_api, "time", fake_time):
        return call(weixin_api.WeixinApi(base_url="https://example.invalid")), calls


def test_without_a_proxy_login_goes_direct():
    result, calls = _run(lambda api: api.fetch_qr_code(), "", [_ok({"qrcode": "q"})])
    assert result == {"qrcode": "q"}
    assert calls == ["direct"]


def test_a_working_proxy_carries_the_login():
    result, calls = _run(lambda api: api.fetch_qr_code(), PROXY, [_ok({"qrcode": "q"})])
    assert result == {"qrcode": "q"}
    assert calls == ["proxy"]


def test_an_unreachable_proxy_falls_back_to_direct():
    result, calls = _run(lambda api: api.fetch_qr_code(), PROXY,
                         [requests.exceptions.ProxyError("refused"), _ok({"qrcode": "q"})])
    assert result == {"qrcode": "q"}
    assert calls == ["proxy", "direct"]


def test_a_hanging_proxy_on_qr_fetch_falls_back_to_direct():
    result, calls = _run(lambda api: api.fetch_qr_code(), PROXY,
                         [requests.exceptions.ReadTimeout("hung"), _ok({"qrcode": "q"})])
    assert result == {"qrcode": "q"}
    assert calls == ["proxy", "direct"]


def test_a_failed_proxy_is_skipped_during_the_cooldown_then_retried():
    _run(lambda api: api.fetch_qr_code(), PROXY,
         [requests.exceptions.ProxyError("refused"), _ok({"qrcode": "q"})], now=1000.0)

    _, calls = _run(lambda api: api.fetch_qr_code(), PROXY, [_ok({"qrcode": "q"})],
                    now=1000.0 + weixin_api.LOGIN_PROXY_COOLDOWN_S - 1)
    assert calls == ["direct"]

    _, calls = _run(lambda api: api.fetch_qr_code(), PROXY, [_ok({"qrcode": "q"})],
                    now=1000.0 + weixin_api.LOGIN_PROXY_COOLDOWN_S + 1)
    assert calls == ["proxy"]


def test_a_long_poll_timeout_through_the_proxy_is_just_a_wait():
    result, calls = _run(lambda api: api.poll_qr_status("q"), PROXY,
                         [requests.exceptions.ReadTimeout("no change yet")])
    assert result == {"status": "wait"}
    assert calls == ["proxy"]
    assert not weixin_api._login_proxy_down_until


def test_an_unreachable_proxy_on_status_poll_falls_back_to_direct():
    result, calls = _run(lambda api: api.poll_qr_status("q"), PROXY,
                         [requests.exceptions.ConnectTimeout("proxy down"), _ok({"status": "scaned"})])
    assert result == {"status": "scaned"}
    assert calls == ["proxy", "direct"]
