# encoding: utf-8
"""How a Weixin QR login ends, and what happens once it has.

A login attempt that ends must say why (for the status report), an expired
session must not retry QR logins forever, and a control-plane replay must
restart an instance whose login has ended so it can issue a new code.
"""

import sys
import types
from unittest.mock import patch

if "linkai" not in sys.modules:
    _linkai = types.ModuleType("linkai")
    _linkai.LinkAIClient = type("LinkAIClient", (), {"__init__": lambda self, *a, **k: None})
    _linkai.PushMsg = type("PushMsg", (), {})
    sys.modules["linkai"] = _linkai

from channel.weixin import weixin_channel as wx  # noqa: E402
import common.cloud_client as cloud_client  # noqa: E402
from common.cloud_client import CloudClient  # noqa: E402

QR = {"qrcode": "QR_abc", "qrcode_img_content": "https://x/y.png"}


class _Stop:
    """Never stops on its own; an untimed wait() stands for "until stopped"."""

    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, timeout=None):
        if timeout is None:
            self.stopped = True
        return self.stopped


class _Api:
    """Every instance draws from one shared status sequence; the last one repeats."""

    def __init__(self, statuses, base_url=""):
        self.statuses = statuses
        self.base_url = base_url
        self.polled_on = []

    def fetch_qr_code(self):
        return dict(QR)

    def poll_qr_status(self, qrcode, timeout=None):
        self.polled_on.append(self.base_url)
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]


def _channel():
    cls = wx.WeixinChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._stop_event = _Stop()
    ch._current_qr_url = ""
    ch._login_error = ""
    ch._credentials_path = "creds.json"
    ch.cloud_mode = False
    return ch


def _login(statuses):
    ch = _channel()
    apis = []
    statuses = list(statuses)

    def _make_api(base_url="", **_kw):
        api = _Api(statuses, base_url)
        apis.append(api)
        return api

    with patch.object(wx, "WeixinApi", side_effect=_make_api), \
            patch.object(ch, "_print_qr", lambda url: None), \
            patch.object(ch, "_notify_cloud_qrcode", lambda url: None), \
            patch("builtins.print", lambda *a, **k: None):
        result = ch._qr_login(base_url="https://origin.test")
    return result, ch, apis


def test_pairing_code_request_ends_the_login_with_a_reason():
    result, ch, _apis = _login([{"status": "need_verifycode"}])
    assert result == {}
    assert "pairing code" in ch._login_error
    assert ch._current_qr_url == ""


def test_already_bound_ends_the_login_with_a_reason():
    result, ch, _apis = _login([{"status": "binded_redirect"}])
    assert result == {}
    assert "already connected" in ch._login_error


def test_redirect_switches_the_polling_host():
    result, _ch, apis = _login([
        {"status": "scaned_but_redirect", "redirect_host": "idc2.test"},
        {"status": "binded_redirect"},
    ])
    assert result == {}
    assert [a.base_url for a in apis] == ["https://origin.test", "https://idc2.test"]
    assert apis[1].polled_on == ["https://idc2.test"]


def test_timeout_records_a_reason():
    with patch.object(wx, "QR_LOGIN_TIMEOUT_S", -1):
        result, ch, _apis = _login([{"status": "wait"}])
    assert result == {}
    assert "timed out" in ch._login_error


# ---------------------------------------------------------------------------
# an expired session re-logs in once, then waits instead of looping
# ---------------------------------------------------------------------------


class _ExpiredApi:
    base_url = "https://origin.test"
    cdn_base_url = ""

    def get_updates(self, _buf):
        return {"ret": -14, "errcode": -14}


def test_failed_relogin_reports_and_stops_retrying():
    ch = _channel()
    ch.api = _ExpiredApi()
    ch._get_updates_buf = ""
    relogins, reports = [], []

    def _relogin():
        relogins.append(1)
        return False

    with patch.object(ch, "_relogin", _relogin), \
            patch.object(ch, "_notify_cloud_status", lambda s, e=None: reports.append((s, e))), \
            patch("builtins.print", lambda *a, **k: None):
        ch._poll_loop()

    assert relogins == [1]
    assert reports and reports[0][0] == "error"


# ---------------------------------------------------------------------------
# a replayed record restarts a Weixin instance that is not logged in
# ---------------------------------------------------------------------------


class _Mgr:
    def __init__(self, login_status):
        self.ch = types.SimpleNamespace(login_status=login_status)

    def get_channel(self, _instance_id):
        return self.ch


def _apply(login_status, channel_type="weixin", restart_waiting_login=False):
    client = CloudClient.__new__(CloudClient)
    client.channel_mgr = _Mgr(login_status)
    started = []

    class _Thread:
        def __init__(self, target=None, args=(), daemon=None):
            self.args = args

        def start(self):
            started.append(self.args)

    record = types.SimpleNamespace(instance_id="abc")
    with patch("channel.channel_instances.get_instance", lambda *a, **k: record), \
            patch("channel.channel_instances.upsert_instance", lambda *a, **k: record), \
            patch.object(cloud_client.threading, "Thread", _Thread), \
            patch.object(CloudClient, "_instance_signature", lambda self, r: "same"), \
            patch.object(CloudClient, "_instance_agent_id", lambda self, d: ""), \
            patch.object(CloudClient, "_instance_credentials_from", lambda self, t, d: {}), \
            patch.object(CloudClient, "_instance_members", lambda self, d: []), \
            patch.object(CloudClient, "_instance_peers", lambda self, d: []):
        restarted = client._apply_instance("abc", channel_type, {},
                                           restart_waiting_login=restart_waiting_login)
    return restarted, started


def test_idle_weixin_instance_is_restarted():
    restarted, started = _apply("idle")
    assert restarted and started


def test_logged_in_weixin_instance_is_left_alone():
    restarted, started = _apply("logged_in", restart_waiting_login=True)
    assert not restarted and not started


def test_waiting_instance_restarts_only_on_explicit_update():
    assert _apply("waiting_scan")[0] is False
    assert _apply("waiting_scan", restart_waiting_login=True)[0] is True


def test_other_channel_types_are_unaffected():
    restarted, _started = _apply("idle", channel_type="feishu")
    assert not restarted
