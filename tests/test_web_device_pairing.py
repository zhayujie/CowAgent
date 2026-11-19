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
    from channel.web.core import _common, devices, identity, pairing

    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COW_DEPLOYMENT", raising=False)
    monkeypatch.setitem(config.conf(), "web_password", PASSWORD)
    monkeypatch.setitem(config.conf(), "web_public_url", "")
    monkeypatch.setitem(config.conf(), "device_name", "")
    identity.reset()
    monkeypatch.setattr(_common, "_SECRETS", {})
    monkeypatch.setattr(devices, "_cache", None)
    monkeypatch.setattr(devices, "_active", {})
    monkeypatch.setattr(devices_api, "lan_urls", lambda: ["http://192.168.1.20:9899"])
    pairing.reset()
    devices_api._pair_limiter.reset("pair")
    yield tmp_path
    pairing.reset()
    identity.reset()


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
        "/api/device", "DeviceSelfHandler",
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
    assert body["auth"]["methods"] == ["password", "pairing"]
    assert body["id"].startswith("dev_")
    assert "name" not in body


def test_the_device_id_survives_a_restart(env):
    from channel.web.core import identity

    _, first = _call(_app(), "/.well-known/cowagent")
    identity.reset()
    _, again = _call(_app(), "/.well-known/cowagent")
    assert first["id"] == again["id"]
    with open(env / "device" / "device_id", encoding="utf-8") as f:
        assert f.read().strip() == first["id"]


def test_a_source_deployment_keeps_device_state_out_of_the_project(tmp_path, monkeypatch):
    from cli import utils as cli_utils

    monkeypatch.delenv("COW_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    path = config.get_device_dir()
    assert os.path.dirname(path) == os.path.join(str(tmp_path), ".cow", "device")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
    assert not path.startswith(config.get_root())
    assert cli_utils.get_device_dir() == path


def test_an_unwritable_home_keeps_the_console_working(env, tmp_path, monkeypatch):
    from channel.web.core import local_control

    home = tmp_path / "home-is-a-file"
    home.write_text("")
    monkeypatch.delenv("COW_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(local_control, "_key", "")
    local_control.publish("127.0.0.1", 9899, "http")
    local_control.withdraw()
    app = _app()
    token = _owner_token(app)
    assert _call(app, "/api/sessions", token=token)[0].status.startswith("200")


def test_each_source_checkout_is_an_instance_of_its_own(tmp_path):
    a = config.source_instance_key(str(tmp_path / "one" / "CowAgent"))
    b = config.source_instance_key(str(tmp_path / "two" / "CowAgent"))
    assert a != b and a.startswith("CowAgent-") and b.startswith("CowAgent-")
    assert config.source_instance_key(str(tmp_path / "one" / "CowAgent")) == a


def test_the_agent_cannot_reach_another_instances_device_directory(tmp_path, monkeypatch):
    from agent.tools.read.read import Read

    monkeypatch.delenv("COW_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    other = tmp_path / ".cow" / "device"
    other.mkdir(parents=True)
    (other / "auth_secret").write_text("x")
    assert Read().execute({"path": str(other / "auth_secret")}).status == "error"


def test_the_agent_file_tools_refuse_the_device_directory(env):
    from agent.tools.edit.edit import Edit
    from agent.tools.read.read import Read
    from agent.tools.write.write import Write
    from channel.web.core import devices

    devices.add("Phone", "ios")
    listed = os.path.join(str(env), "device", "devices.json")
    assert Read().execute({"path": listed}).status == "error"
    assert Write().execute({"path": listed, "content": "{}"}).status == "error"
    assert Edit().execute({"path": listed, "oldText": "Phone", "newText": "Mine"}).status == "error"
    assert Write().execute({"path": os.path.join(str(env), "device", "auth_secret"), "content": "x"}).status == "error"
    assert "Phone" in open(listed, encoding="utf-8").read()


def test_the_id_and_name_come_from_the_device_directory_and_config(env, monkeypatch):
    (env / "device").mkdir(exist_ok=True)
    (env / "device" / "device_id").write_text("ins-7f3a9c")
    monkeypatch.setitem(config.conf(), "device_name", "Team assistant")
    app = _app()
    _, found = _call(app, "/.well-known/cowagent")
    assert found["id"] == "ins-7f3a9c"
    _, listed = _call(app, "/api/devices", token=_owner_token(app))
    assert listed["instance"]["id"] == "ins-7f3a9c"
    assert listed["instance"]["name"] == "Team assistant"


def test_the_name_defaults_to_the_computers_and_can_be_changed(env, monkeypatch):
    from channel.web.core import identity

    monkeypatch.setattr(identity, "_system_name", "Studio Mac")
    app = _app()
    owner = _owner_token(app)
    _, listed = _call(app, "/api/devices", token=owner)
    assert listed["instance"]["name"] == "Studio Mac"

    res, _ = _call(app, "/api/device", "PATCH", {"name": "Office"})
    assert res.status.startswith("401")
    _, renamed = _call(app, "/api/device", "PATCH", {"name": "  Office \n server  "}, token=owner)
    assert renamed["instance"]["name"] == "Office server"
    with open(env / "config.json", encoding="utf-8") as f:
        assert json.load(f)["device_name"] == "Office server"
    _, created = _call(app, "/api/pairing", "POST", {}, token=owner)
    assert created["instance"]["name"] == "Office server"

    _, reset = _call(app, "/api/device", "PATCH", {"name": ""}, token=owner)
    assert reset["instance"]["name"] == "Studio Mac"
    assert reset["instance"]["managed"] is False


def test_a_managed_deployment_says_so_and_works_the_same(env, monkeypatch):
    monkeypatch.setenv("COW_DEPLOYMENT", "managed")
    monkeypatch.setitem(config.conf(), "web_password", "")
    monkeypatch.setitem(config.conf(), "device_name", "Team assistant")
    app = _app()
    _, listed = _call(app, "/api/devices")
    assert listed["instance"] == {**listed["instance"], "name": "Team assistant", "managed": True}
    _, found = _call(app, "/.well-known/cowagent")
    assert found["auth"]["methods"] == ["password", "pairing"]
    _, created = _call(app, "/api/pairing", "POST", {"base_url": "https://agent.example.com"})
    assert created["status"] == "success"
    # Whoever runs it names it through the same call.
    _, renamed = _call(app, "/api/device", "PATCH", {"name": "Sales assistant"})
    assert renamed["instance"]["name"] == "Sales assistant"


def test_container_hostnames_are_not_shown_as_names(env, monkeypatch):
    from channel.web.core import identity

    monkeypatch.setattr(identity.sys, "platform", "linux")
    monkeypatch.setattr(identity, "_linux_pretty_name", lambda: "")
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "3f9a1c2b7d4e")
    assert identity.device_name() == "CowAgent"
    identity.reset()
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "nas.local")
    assert identity.device_name() == "nas"


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


def test_loopback_public_url_is_not_offered(env, monkeypatch):
    monkeypatch.setitem(config.conf(), "web_public_url", "http://127.0.0.1:9899")
    app = _app()
    _, created = _call(app, "/api/pairing", "POST", {}, token=_owner_token(app))
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
    path = os.path.join(str(env), "device", "devices.json")
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


def test_a_password_changed_outside_the_console_signs_out_password_devices(env, monkeypatch):
    app = _app()
    browser = _owner_token(app)
    _, phone = _pair(app, browser)
    monkeypatch.setitem(config.conf(), "web_password", "edited-in-config-json")
    assert _call(app, "/api/sessions", token=browser)[0].status.startswith("401")
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


def test_a_browser_in_use_gets_its_cookie_again_once_a_day(env, monkeypatch):
    from channel.web.core import _common

    monkeypatch.setattr(_common, "_cookie_given_at", {})
    app = _app()
    _, body = _call(app, "/auth/login", "POST", {"password": PASSWORD})
    cookie = {"Cookie": f"cow_auth_token={body['token']}"}
    res, _ = _call(app, "/api/sessions", headers=cookie)
    assert "Set-Cookie" not in res.headers

    clock = _common.time.time() + 86400 + 1
    monkeypatch.setattr(_common.time, "time", lambda: clock)
    res, _ = _call(app, "/api/sessions", headers=cookie)
    assert f"cow_auth_token={body['token']}" in res.headers.get("Set-Cookie", "")
    assert "HttpOnly" in res.headers["Set-Cookie"]
    res, _ = _call(app, "/api/sessions", headers=cookie)
    assert "Set-Cookie" not in res.headers


def test_a_header_token_never_sets_a_cookie(env, monkeypatch):
    from channel.web.core import _common

    monkeypatch.setattr(_common, "_cookie_given_at", {})
    app = _app()
    token = _owner_token(app)
    _common._cookie_given_at.clear()
    res, _ = _call(app, "/api/sessions", token=token)
    assert "Set-Cookie" not in res.headers


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
    _, listed = _call(app, "/api/devices", token=me)
    assert listed["current"] == me.split(".")[1]


def test_setting_the_first_password_keeps_the_caller_signed_in(env, monkeypatch):
    monkeypatch.setitem(config.conf(), "web_password", "")
    app = _app()
    _, body = _call(app, "/config", "POST", {"updates": {"web_password": "first-password-1"}})
    assert body["auth_token"].startswith("cowd.")
    assert _call(app, "/api/sessions", token=body["auth_token"])[0].status.startswith("200")


def test_the_first_password_signs_out_devices_paired_while_open(env, monkeypatch):
    monkeypatch.setitem(config.conf(), "web_password", "")
    app = _app()
    _, phone = _pair(app, "")
    assert phone["status"] == "success"
    _, body = _call(app, "/config", "POST", {"updates": {"web_password": "first-password-1"}})
    assert _call(app, "/api/sessions", token=body["auth_token"])[0].status.startswith("200")
    assert _call(app, "/api/sessions", token=phone["token"])[0].status.startswith("401")


@pytest.mark.parametrize("headers, seen", [
    ({"HTTP_X_FORWARDED_FOR": "1.2.3.4, 203.0.113.9"}, "203.0.113.9"),
    ({"HTTP_X_FORWARDED_FOR": "1.2.3.4, 203.0.113.9", "HTTP_X_REAL_IP": "198.51.100.7"}, "198.51.100.7"),
    ({}, "127.0.0.1"),
])
def test_the_client_address_is_what_the_local_proxy_saw(monkeypatch, headers, seen):
    from channel.web.core import _common

    monkeypatch.setattr(web, "ctx", web.storage(env={"REMOTE_ADDR": "127.0.0.1", **headers}))
    assert _common._client_ip() == seen


def test_forwarding_headers_from_elsewhere_are_ignored(monkeypatch):
    from channel.web.core import _common

    monkeypatch.setattr(web, "ctx", web.storage(env={"REMOTE_ADDR": "192.168.1.50",
                                                     "HTTP_X_REAL_IP": "10.0.0.1"}))
    assert _common._client_ip() == "192.168.1.50"


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
    path = os.path.join(str(env), "device", "devices.json")
    before = os.stat(path).st_mtime_ns
    writes = []
    monkeypatch.setattr(devices, "_save", lambda doc: writes.append(doc))
    for _ in range(5):
        assert devices.verify(token)
    assert writes == [] and os.stat(path).st_mtime_ns == before
