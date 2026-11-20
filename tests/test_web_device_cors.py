# encoding:utf-8
"""A console on another origin, paired with this server, may call it.

Pairing from a page records that page's origin on the device. From then on the
origin passes the cross-site checks and can read replies, but only together
with that device's token; any other site, or the same site with another
token, is still turned away. Removing the device closes the origin again.
"""

import io
import json

import pytest
import web

import config

PASSWORD = "owner-secret-pass"
HOST = "192.168.1.20:9899"
CONSOLE = "http://localhost:9914"


@pytest.fixture
def server(tmp_path, monkeypatch):
    from channel.web.api import auth as auth_api
    from channel.web.api import devices as devices_api
    from channel.web.api import sessions as sessions_api
    from channel.web.core import _common, devices, pairing
    from channel.web.core.request_guard import guard_requests

    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.setitem(config.conf(), "web_password", PASSWORD)
    monkeypatch.setitem(config.conf(), "web_public_url", "")
    monkeypatch.setattr(_common, "_SECRETS", {})
    monkeypatch.setattr(devices, "_cache", None)
    monkeypatch.setattr(devices, "_active", {})
    monkeypatch.setattr(devices_api, "lan_urls", lambda: [f"http://{HOST}"])
    pairing.reset()
    devices_api._pair_limiter.reset("pair")

    urls = (
        "/auth/login", "AuthLoginHandler",
        "/auth/pair", "AuthPairHandler",
        "/.well-known/cowagent", "WellKnownHandler",
        "/api/pairing", "PairingHandler",
        "/api/devices/(d_[0-9a-f]+)", "DeviceHandler",
        "/api/sessions", "SessionsHandler",
    )
    mapping = dict(vars(devices_api))
    mapping["AuthLoginHandler"] = auth_api.AuthLoginHandler
    mapping["SessionsHandler"] = sessions_api.SessionsHandler
    yield guard_requests(web.application(urls, mapping, autoreload=False).wsgifunc())
    pairing.reset()


def _call(app, path, method="GET", body=None, token="", origin="", preflight=False, site=""):
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)
    data = json.dumps(body).encode() if body is not None else b""
    env = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
        "HTTP_HOST": HOST, "SERVER_NAME": "192.168.1.20", "SERVER_PORT": "9899",
        "SERVER_PROTOCOL": "HTTP/1.1", "REMOTE_ADDR": "192.168.1.30",
        "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(data),
        "CONTENT_LENGTH": str(len(data)), "CONTENT_TYPE": "application/json",
    }
    if token:
        env["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    if origin:
        env["HTTP_ORIGIN"] = origin
        env["HTTP_SEC_FETCH_SITE"] = "cross-site"
    if site:
        env["HTTP_SEC_FETCH_SITE"] = site
    if preflight:
        env["HTTP_ACCESS_CONTROL_REQUEST_METHOD"] = "POST"
        env["HTTP_ACCESS_CONTROL_REQUEST_HEADERS"] = "authorization,content-type"
    seen = {}

    def start_response(status, headers, exc_info=None):
        seen["status"], seen["headers"] = status, headers

    out = b"".join(app(env, start_response))
    headers = {}
    for name, value in seen["headers"]:
        headers.setdefault(name.lower(), value)
    payload = json.loads(out) if out.strip().startswith(b"{") else None
    return seen["status"], headers, payload


def _owner(app):
    return _call(app, "/auth/login", "POST", {"password": PASSWORD})[2]["token"]


def _pair_from(app, origin, owner=None):
    owner = owner or _owner(app)
    created = _call(app, "/api/pairing", "POST", {}, token=owner)[2]
    status, headers, paired = _call(app, "/auth/pair", "POST",
                                    {"code": created["code"], "device": {"name": "Console", "platform": "web"}},
                                    origin=origin)
    return status, headers, paired


def test_any_page_may_ask_what_this_is_and_redeem_a_code(server):
    status, headers, _ = _call(server, "/.well-known/cowagent", origin="https://anywhere.example")
    assert status.startswith("200") and headers["access-control-allow-origin"] == "https://anywhere.example"

    status, headers, _ = _call(server, "/auth/pair", "OPTIONS", origin=CONSOLE, preflight=True)
    assert status.startswith("204") and headers["access-control-allow-origin"] == CONSOLE

    status, headers, paired = _pair_from(server, CONSOLE)
    assert paired["status"] == "success"
    assert headers["access-control-allow-origin"] == CONSOLE
    assert paired["device"]["origin"] == CONSOLE


def test_the_paired_origin_calls_with_its_own_token(server):
    _, _, paired = _pair_from(server, CONSOLE)
    status, headers, _ = _call(server, "/api/sessions", "OPTIONS", origin=CONSOLE, preflight=True)
    assert status.startswith("204")
    assert "authorization" in headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in headers

    status, headers, _ = _call(server, "/api/sessions", token=paired["token"], origin=CONSOLE)
    assert status.startswith("200") and headers["access-control-allow-origin"] == CONSOLE
    assert "Origin" in headers["vary"]


def test_loopback_names_count_as_one_origin(server):
    _, _, paired = _pair_from(server, CONSOLE)
    other_name = "http://127.0.0.1:9914"
    status, headers, _ = _call(server, "/api/sessions", token=paired["token"], origin=other_name)
    assert status.startswith("200") and headers["access-control-allow-origin"] == other_name


def test_a_write_from_the_paired_origin_passes_the_cross_site_check(server):
    _, _, paired = _pair_from(server, CONSOLE)
    status, _, body = _call(server, f"/api/devices/{paired['device']['id']}", "PATCH",
                            {"name": "My laptop"}, token=paired["token"], origin=CONSOLE)
    assert status.startswith("200") and body["device"]["name"] == "My laptop"


def test_another_site_gets_nothing_even_holding_the_token(server):
    _, _, paired = _pair_from(server, CONSOLE)
    evil = "https://evil.example"
    status, headers, _ = _call(server, "/api/sessions", "OPTIONS", origin=evil, preflight=True)
    assert "access-control-allow-origin" not in headers
    status, headers, _ = _call(server, "/api/sessions", token=paired["token"], origin=evil)
    assert "access-control-allow-origin" not in headers
    status, _, _ = _call(server, f"/api/devices/{paired['device']['id']}", "PATCH",
                         {"name": "pwned"}, token=paired["token"], origin=evil)
    assert status.startswith("403")


def test_the_paired_origin_cannot_borrow_another_devices_token(server):
    _pair_from(server, CONSOLE)
    native = _pair_from(server, "")[2]["token"]
    status, headers, _ = _call(server, "/api/sessions", token=native, origin=CONSOLE)
    assert "access-control-allow-origin" not in headers
    status, _, _ = _call(server, "/api/pairing", "POST", {}, token=native, origin=CONSOLE)
    assert status.startswith("403")


def test_password_sign_in_is_not_open_to_other_origins(server):
    _pair_from(server, CONSOLE)
    status, headers, _ = _call(server, "/auth/login", "POST", {"password": PASSWORD}, origin=CONSOLE)
    assert status.startswith("403") and "access-control-allow-origin" not in headers


def test_removing_the_device_closes_its_origin(server):
    owner = _owner(server)
    _, _, paired = _pair_from(server, CONSOLE, owner)
    _call(server, f"/api/devices/{paired['device']['id']}", "DELETE", token=owner)
    status, headers, _ = _call(server, "/api/sessions", "OPTIONS", origin=CONSOLE, preflight=True)
    assert "access-control-allow-origin" not in headers
    status, headers, _ = _call(server, "/api/sessions", token=paired["token"], origin=CONSOLE)
    assert status.startswith("401") and "access-control-allow-origin" not in headers


def test_a_native_client_records_no_origin(server):
    _, _, paired = _pair_from(server, "")
    assert paired["device"]["origin"] == ""


@pytest.mark.parametrize("origin", ["", "null"])
def test_the_desktop_app_writes_to_a_remote_instance_with_its_device_token(server, origin):
    # A file:// page sends no origin (or "null") and is cross-site to everything.
    token = _pair_from(server, "")[2]["token"]
    status, _, body = _call(server, "/api/pairing", "POST", {}, token=token, site="cross-site",
                            **({"origin": origin} if origin else {}))
    assert status.startswith("200") and body["status"] == "success"
    status, _, _ = _call(server, "/api/pairing", "POST", {}, site="cross-site")
    assert status.startswith("403")


def test_a_web_paired_token_is_not_a_pass_for_pages_without_an_origin(server):
    _, _, paired = _pair_from(server, CONSOLE)
    status, _, _ = _call(server, "/api/pairing", "POST", {}, token=paired["token"], site="cross-site")
    assert status.startswith("403")
