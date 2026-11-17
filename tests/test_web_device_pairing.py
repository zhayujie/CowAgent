# encoding:utf-8
"""Pairing a device by one-time code, and the device tokens that come of it.

A code is redeemed once, within its lifetime, for a token belonging to that
device alone; the token works everywhere a session does until the device is
removed or signs out, and the store never holds anything that could be
replayed.
"""

import json
import os
import stat
from urllib.parse import parse_qs, urlsplit

import pytest
import web

import config

PASSWORD = "owner-secret-pass"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from channel.web.api import devices as devices_api
    from channel.web.core import _common, devices, pairing

    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.setitem(config.conf(), "web_password", PASSWORD)
    monkeypatch.setitem(config.conf(), "web_public_url", "")
    monkeypatch.setattr(_common, "_SECRETS", {})
    monkeypatch.setattr(devices, "_cache", None)
    monkeypatch.setattr(devices, "_active", {})
    monkeypatch.setattr(devices_api, "lan_urls", lambda: ["http://192.168.1.20:9899"])
    pairing.reset()
    devices_api._pair_limiter.reset("pair")
    yield tmp_path
    pairing.reset()


def _app():
    from channel.web.api import auth as auth_api
    from channel.web.api import devices as devices_api
    from channel.web.api import sessions as sessions_api

    urls = (
        "/auth/login", "AuthLoginHandler",
        "/auth/logout", "AuthLogoutHandler",
        "/auth/pair", "AuthPairHandler",
        "/.well-known/cowagent", "WellKnownHandler",
        "/api/pairing", "PairingHandler",
        "/api/pairing/(p_[0-9a-f]+)", "PairingStatusHandler",
        "/api/devices", "DevicesHandler",
        "/api/devices/revoke_others", "DevicesRevokeOthersHandler",
        "/api/devices/(d_[0-9a-f]+)", "DeviceHandler",
        "/api/sessions", "SessionsHandler",
        "/config", "ConfigHandler",
    )
    from channel.web.api import config as config_api

    mapping = dict(vars(devices_api))
    mapping["AuthLoginHandler"] = auth_api.AuthLoginHandler
    mapping["AuthLogoutHandler"] = auth_api.AuthLogoutHandler
    mapping["SessionsHandler"] = sessions_api.SessionsHandler
    mapping["ConfigHandler"] = config_api.ConfigHandler
    return web.application(urls, mapping, autoreload=False)


def _call(app, path, method="GET", body=None, token="", headers=None):
    sent = {"Content-Type": "application/json", **(headers or {})}
    if token:
        sent["Authorization"] = f"Bearer {token}"
    res = app.request(path, method=method, headers=sent,
                      data=json.dumps(body) if body is not None else None)
    return res, (json.loads(res.data) if res.data.strip().startswith(b"{") else None)


def _paired(listed):
    return {d["name"] for d in listed["devices"] if d["via"] == "pairing"}


def _owner_token(app):
    _, body = _call(app, "/auth/login", "POST", {"password": PASSWORD})
    return body["token"]


def _pair(app, owner, device=None, use="secret"):
    _, created = _call(app, "/api/pairing", "POST", {}, token=owner)
    code = created["code"] if use == "code" else parse_qs(urlsplit(created["link"]).query)["c"][0]
    _, paired = _call(app, "/auth/pair", "POST",
                      {"code": code, "device": device or {"name": "Pixel 9", "platform": "android"}})
    return created, paired


def test_discovery_says_what_answered_without_credentials(env):
    res, body = _call(_app(), "/.well-known/cowagent")
    assert res.status.startswith("200")
    assert body["type"] == "instance" and body["protocol"] == 1
    assert body["auth"]["required"] is True
    assert "name" not in body


def test_creating_a_code_needs_a_signed_in_client(env):
    res, _ = _call(_app(), "/api/pairing", "POST", {})
    assert res.status.startswith("401")


def test_qr_link_carries_secret_and_addresses(env):
    app = _app()
    _, created = _call(app, "/api/pairing", "POST", {"base_url": "https://agent.example.com/chat"},
                       token=_owner_token(app))
    assert created["status"] == "success"
    link = urlsplit(created["link"])
    assert f"{link.scheme}://{link.netloc}" == "cowagent://pair"
    query = parse_qs(link.query)
    assert query["v"] == ["1"] and len(query["c"][0]) >= 24
    assert query["u"] == ["https://agent.example.com", "http://192.168.1.20:9899"]
    assert len(created["code"]) == 9 and created["code"][4] == "-"


def test_loopback_page_address_is_not_offered(env):
    app = _app()
    _, created = _call(app, "/api/pairing", "POST", {"base_url": "http://127.0.0.1:9899"},
                       token=_owner_token(app))
    assert created["urls"] == ["http://192.168.1.20:9899"]


@pytest.fixture
def console(env, monkeypatch):
    from channel.web.core import local_control

    monkeypatch.setattr(local_control, "_key", "")
    monkeypatch.setattr(local_control, "_host", "")
    local_control.publish("0.0.0.0", 9899, "http")
    with open(local_control.path(), encoding="utf-8") as f:
        return json.load(f)


def _local(app, path, method="GET", key="", addr="127.0.0.1", headers=None):
    sent = {"Content-Type": "application/json", **(headers or {})}
    if key:
        sent["X-Cow-Local-Key"] = key
    res = app.request(path, method=method, headers=sent, env={"REMOTE_ADDR": addr},
                      data=json.dumps({}) if method == "POST" else None)
    return res, (json.loads(res.data) if res.data.strip().startswith(b"{") else None)


def test_console_file_is_private_and_points_at_loopback(env, console):
    from channel.web.core import local_control

    assert console["url"] == "http://127.0.0.1:9899"
    assert console["pid"] == os.getpid() and len(console["key"]) >= 32
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(local_control.path()).st_mode) == 0o600
    local_control.withdraw()
    assert not os.path.exists(local_control.path())


def test_the_cli_creates_a_code_with_the_local_key(env, console):
    app = _app()
    res, created = _local(app, "/api/pairing", "POST", key=console["key"])
    assert created["status"] == "success" and created["instance"]["name"]
    _, state = _local(app, f"/api/pairing/{created['pairing_id']}", key=console["key"])
    assert state["state"] == "pending"
    # The key opens pairing only, not the rest of the console.
    res, _ = _local(app, "/api/devices", key=console["key"])
    assert res.status.startswith("401")


@pytest.mark.parametrize("case", ["wrong_key", "remote", "proxied"])
def test_the_local_key_only_works_from_this_machine(env, console, case):
    key = "x" * 43 if case == "wrong_key" else console["key"]
    addr = "192.168.1.30" if case == "remote" else "127.0.0.1"
    headers = {"X-Forwarded-For": "203.0.113.9"} if case == "proxied" else None
    res, _ = _local(_app(), "/api/pairing", "POST", key=key, addr=addr, headers=headers)
    assert res.status.startswith("401")


def test_unreachable_instance_cannot_pair(env, monkeypatch):
    from channel.web.api import devices as devices_api

    monkeypatch.setattr(devices_api, "lan_urls", lambda: [])
    app = _app()
    _, body = _call(app, "/api/pairing", "POST", {}, token=_owner_token(app))
    assert body["status"] == "error" and body["reason"] == "local_only"


@pytest.mark.parametrize("use", ["secret", "code"])
def test_redeemed_token_signs_in(env, use):
    app = _app()
    created, paired = _pair(app, _owner_token(app), use=use)
    assert paired["status"] == "success"
    assert paired["token"].startswith("cowd.")
    assert paired["device"]["name"] == "Pixel 9"
    res, _ = _call(app, "/api/sessions", token=paired["token"])
    assert res.status.startswith("200")
    _, status = _call(app, f"/api/pairing/{created['pairing_id']}", token=_owner_token(app))
    assert status["state"] == "paired" and status["device"]["id"] == paired["device"]["id"]


def test_short_code_tolerates_case_and_separators(env):
    app = _app()
    _, created = _call(app, "/api/pairing", "POST", {}, token=_owner_token(app))
    typed = " " + created["code"].lower().replace("-", " ") + " "
    _, paired = _call(app, "/auth/pair", "POST", {"code": typed, "device": {"name": "x"}})
    assert paired["status"] == "success"


def test_a_code_works_once(env):
    app = _app()
    _, created = _call(app, "/api/pairing", "POST", {}, token=_owner_token(app))
    _, first = _call(app, "/auth/pair", "POST", {"code": created["code"]})
    _, second = _call(app, "/auth/pair", "POST", {"code": created["code"]})
    assert first["status"] == "success"
    assert second["reason"] == "invalid_code"


def test_expired_code_is_refused(env, monkeypatch):
    from channel.web.core import pairing

    app = _app()
    _, created = _call(app, "/api/pairing", "POST", {}, token=_owner_token(app))
    pairing.get(created["pairing_id"]).expires_at = 0
    _, body = _call(app, "/auth/pair", "POST", {"code": created["code"]})
    assert body["reason"] == "invalid_code"


def test_only_a_few_codes_stay_live(env):
    from channel.web.core import pairing

    first = pairing.create()
    for _ in range(pairing.MAX_ACTIVE):
        pairing.create()
    assert pairing.claim(first.code) is None


def test_wrong_codes_lock_the_client_out(env):
    app = _app()
    owner = _owner_token(app)
    for _ in range(10):
        _call(app, "/auth/pair", "POST", {"code": "AAAA-AAAA"})
    _, created = _call(app, "/api/pairing", "POST", {}, token=owner)
    _, body = _call(app, "/auth/pair", "POST", {"code": created["code"]})
    assert body["reason"] == "locked" and body["retry_after"] > 0


def test_store_keeps_hashes_only_and_is_private(env):
    app = _app()
    _, paired = _pair(app, _owner_token(app))
    path = os.path.join(str(env), "devices.json")
    raw = open(path, encoding="utf-8").read()
    secret = paired["token"].rsplit(".", 1)[1]
    assert secret not in raw and "sha256:" in raw
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_token_survives_a_restart(env, monkeypatch):
    from channel.web.core import devices

    app = _app()
    _, paired = _pair(app, _owner_token(app))
    monkeypatch.setattr(devices, "_cache", None)
    res, _ = _call(app, "/api/sessions", token=paired["token"])
    assert res.status.startswith("200")


def test_forged_or_mangled_tokens_fail(env):
    app = _app()
    _, paired = _pair(app, _owner_token(app))
    device_id = paired["device"]["id"]
    for token in (paired["token"] + "x", f"cowd.{device_id}.", f"cowd.d_000000000000.{'a' * 43}", "cowd."):
        res, _ = _call(app, "/api/sessions", token=token)
        assert res.status.startswith("401"), token


def test_removing_a_device_revokes_only_its_token(env):
    app = _app()
    owner = _owner_token(app)
    _, phone = _pair(app, owner)
    _, tablet = _pair(app, owner, device={"name": "iPad", "platform": "ios"})
    _, listed = _call(app, "/api/devices", token=tablet["token"])
    assert _paired(listed) == {"Pixel 9", "iPad"}
    assert listed["current"] == tablet["device"]["id"]
    assert all("secret_hash" not in d for d in listed["devices"])

    res, _ = _call(app, f"/api/devices/{phone['device']['id']}", "DELETE", token=owner)
    assert res.status.startswith("200")
    assert _call(app, "/api/sessions", token=phone["token"])[0].status.startswith("401")
    assert _call(app, "/api/sessions", token=tablet["token"])[0].status.startswith("200")


def test_rename_device(env):
    app = _app()
    owner = _owner_token(app)
    _, phone = _pair(app, owner)
    _, body = _call(app, f"/api/devices/{phone['device']['id']}", "PATCH",
                    {"name": "  My   phone  "}, token=owner)
    assert body["device"]["name"] == "My phone"


def test_device_sign_out_gives_its_token_up(env):
    app = _app()
    _, phone = _pair(app, _owner_token(app))
    _call(app, "/auth/logout", "POST", {}, token=phone["token"])
    assert _call(app, "/api/sessions", token=phone["token"])[0].status.startswith("401")


def test_password_change_keeps_paired_devices(env, monkeypatch):
    app = _app()
    _, phone = _pair(app, _owner_token(app))
    monkeypatch.setitem(config.conf(), "web_password", "a-new-password")
    assert _call(app, "/api/sessions", token=phone["token"])[0].status.startswith("200")


def test_signing_in_with_the_password_is_a_device_too(env):
    app = _app()
    res, body = _call(app, "/auth/login", "POST",
                      {"password": PASSWORD, "device": {"name": "Work phone", "platform": "android"}})
    assert body["token"].startswith("cowd.")
    assert "cow_auth_token=cowd." in res.headers.get("Set-Cookie", "")
    _, listed = _call(app, "/api/devices", token=body["token"])
    me = next(d for d in listed["devices"] if d["id"] == listed["current"])
    assert (me["name"], me["platform"], me["via"]) == ("Work phone", "android", "password")
    assert me["online"] is True
    assert listed["instance"]["name"] and listed["password_set"] is True


def test_a_browser_is_named_after_itself(env):
    app = _app()
    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
    _, body = _call(app, "/auth/login", "POST", {"password": PASSWORD}, headers={"User-Agent": ua})
    _, listed = _call(app, "/api/devices", token=body["token"])
    me = next(d for d in listed["devices"] if d["id"] == listed["current"])
    assert (me["name"], me["platform"]) == ("Chrome · macOS", "web")


def test_the_console_cookie_is_a_device_and_signing_out_revokes_it(env):
    app = _app()
    _, body = _call(app, "/auth/login", "POST", {"password": PASSWORD})
    cookie = {"Cookie": f"cow_auth_token={body['token']}"}
    assert _call(app, "/api/sessions", headers=cookie)[0].status.startswith("200")
    _call(app, "/auth/logout", "POST", {}, headers=cookie)
    assert _call(app, "/api/sessions", headers=cookie)[0].status.startswith("401")


def test_signing_out_every_other_device(env):
    app = _app()
    owner = _owner_token(app)
    _, phone = _pair(app, owner)
    other_browser = _owner_token(app)
    _, body = _call(app, "/api/devices/revoke_others", "POST", {}, token=owner)
    assert body["removed"] == 2
    assert _call(app, "/api/sessions", token=owner)[0].status.startswith("200")
    for token in (phone["token"], other_browser):
        assert _call(app, "/api/sessions", token=token)[0].status.startswith("401")


def test_a_new_password_signs_out_password_devices_but_not_paired_ones(env):
    app = _app()
    me = _owner_token(app)
    other_browser = _owner_token(app)
    _, phone = _pair(app, me)
    _, body = _call(app, "/config", "POST", {"updates": {"web_password": "a-brand-new-pass"}}, token=me)
    assert body["status"] == "success" and "auth_token" not in body
    assert _call(app, "/api/sessions", token=me)[0].status.startswith("200")
    assert _call(app, "/api/sessions", token=phone["token"])[0].status.startswith("200")
    assert _call(app, "/api/sessions", token=other_browser)[0].status.startswith("401")


def test_setting_the_first_password_keeps_the_caller_signed_in(env, monkeypatch):
    monkeypatch.setitem(config.conf(), "web_password", "")
    app = _app()
    _, body = _call(app, "/config", "POST", {"updates": {"web_password": "first-password-1"}})
    assert body["auth_token"].startswith("cowd.")
    assert _call(app, "/api/sessions", token=body["auth_token"])[0].status.startswith("200")


def test_an_unused_device_lapses(env, monkeypatch):
    from channel.web.core import devices

    device, token = devices.add("Old phone", "ios")
    monkeypatch.setattr(devices, "_active", {})
    devices._load()["devices"][0]["last_seen_at"] = 1
    assert devices.verify(token) is None
    assert devices.list_devices() == []


def test_last_use_is_written_sparingly(env, monkeypatch):
    from channel.web.core import devices

    device, token = devices.add("Phone", "ios")
    path = os.path.join(str(env), "devices.json")
    before = os.stat(path).st_mtime_ns
    writes = []
    monkeypatch.setattr(devices, "_save", lambda doc: writes.append(doc))
    for _ in range(5):
        assert devices.verify(token)
    assert writes == [] and os.stat(path).st_mtime_ns == before
