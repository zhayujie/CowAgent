# encoding:utf-8
"""Console session tokens are signed with a random secret, not the password.

A token signed with the password let anyone holding one (a sniffed request, a
log line) guess the password offline. The password is still bound in, so
changing it signs every session out.
"""

import hashlib
import hmac
import os
import stat
import time

import pytest

PASSWORD = "correct horse"


@pytest.fixture
def core(tmp_path, monkeypatch):
    from channel.web.core import _common

    password = {"value": PASSWORD}
    monkeypatch.setattr(_common, "get_device_dir", lambda: str(tmp_path))
    monkeypatch.setattr(_common, "_SECRETS", {})
    monkeypatch.setattr(_common, "_get_web_password", lambda: password["value"])
    monkeypatch.setattr(_common, "_session_expire_seconds", lambda: 86400)
    _common.password = password
    return _common


def test_issued_token_verifies(core):
    assert core._verify_auth_token(core._create_auth_token()) is True


def _password_keyed(password, ts):
    ts_hex = format(int(ts), "x")
    return f"{ts_hex}.{hmac.new(password.encode(), ts_hex.encode(), hashlib.sha256).hexdigest()}"


def test_password_keyed_token_still_verifies_until_it_expires(core):
    # Sessions issued by older versions must survive an upgrade.
    assert core._verify_auth_token(_password_keyed(PASSWORD, time.time())) is True
    assert core._verify_auth_token(_password_keyed(PASSWORD, time.time() - 2 * 86400)) is False


def test_password_keyed_token_stops_with_a_new_password(core):
    token = _password_keyed(PASSWORD, time.time())
    core.password["value"] = "another one"
    assert core._verify_auth_token(token) is False


def test_changing_the_password_signs_sessions_out(core):
    token = core._create_auth_token()
    core.password["value"] = "another one"
    assert core._verify_auth_token(token) is False


def test_secret_survives_a_restart(core):
    token = core._create_auth_token()
    core._SECRETS.clear()
    assert core._verify_auth_token(token) is True


def test_a_new_secret_signs_sessions_out(core, tmp_path):
    token = core._create_auth_token()
    core._SECRETS.clear()
    os.remove(tmp_path / "auth_secret")
    assert core._verify_auth_token(token) is False


def test_secret_file_is_private(core, tmp_path):
    core._create_auth_token()
    mode = stat.S_IMODE(os.stat(tmp_path / "auth_secret").st_mode)
    assert mode == 0o600
