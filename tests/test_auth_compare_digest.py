# encoding:utf-8
"""A rejected credential must be a 401, not a 500.

``hmac.compare_digest`` raises ``TypeError`` when a ``str`` operand contains
non-ASCII characters, so every signature check that handed it a value straight
off the request turned "wrong credential" into an unhandled exception. The
console's login, preview, OpenAI-compatible and token-verify paths were all
reachable without authenticating first, so a single request was enough.
"""

import base64
import hashlib
import hmac
import time

import pytest

from common.utils import constant_time_equals

PASSWORD = "s3cret-preview-key"
PREVIEW_SECRET = b"preview-secret-for-tests"

# A signature the stdlib refuses outright.
NON_ASCII = "\u00e9" * 64


AUTH_SECRET = b"auth-secret-for-tests"


def _token(password: str, ts: int) -> str:
    ts_hex = format(ts, "x")
    pw_tag = hmac.new(AUTH_SECRET, password.encode(), hashlib.sha256).hexdigest()[:16]
    return ts_hex, hmac.new(AUTH_SECRET, f"{ts_hex}.{pw_tag}".encode(), hashlib.sha256).hexdigest()


# --- the helper itself -------------------------------------------------------


def test_equal_and_unequal_strings():
    assert constant_time_equals("abc", "abc") is True
    assert constant_time_equals("abc", "abd") is False
    assert constant_time_equals("", "") is True


def test_non_ascii_operand_does_not_raise():
    """compare_digest raises TypeError here; the helper must answer False."""
    assert constant_time_equals(NON_ASCII, "a" * 64) is False
    assert constant_time_equals("a" * 64, NON_ASCII) is False


def test_non_ascii_values_still_compare_equal():
    # A password may legitimately be non-ASCII, so equality must survive.
    assert constant_time_equals("\u5bc6\u7801", "\u5bc6\u7801") is True
    assert constant_time_equals("\u5bc6\u7801", "\u5bc6\u7802") is False


def test_lone_surrogate_does_not_raise():
    # JSON and query strings can carry lone surrogates; encoding them without
    # surrogatepass would raise UnicodeEncodeError and bring the 500 back.
    assert constant_time_equals("\ud800", "a") is False
    assert constant_time_equals("\ud800", "\ud800") is True


# --- the console token check -------------------------------------------------


@pytest.fixture
def core(monkeypatch):
    from channel.web.core import _common

    monkeypatch.setattr(_common, "_get_web_password", lambda: PASSWORD)
    monkeypatch.setattr(_common, "_get_auth_secret", lambda: AUTH_SECRET)
    monkeypatch.setattr(_common, "_session_expire_seconds", lambda: 86400)
    return _common


def test_valid_token_is_accepted(core):
    ts_hex, sig = _token(PASSWORD, int(time.time()))
    assert core._verify_auth_token(f"{ts_hex}.{sig}") is True


def test_wrong_signature_is_rejected(core):
    ts_hex, _ = _token(PASSWORD, int(time.time()))
    assert core._verify_auth_token(f"{ts_hex}.{'0' * 64}") is False


@pytest.mark.parametrize("sig", [NON_ASCII, "\u4e2d\u6587" * 8, "\ud800", "x" * 63, "x" * 65, ""])
def test_malformed_signature_is_rejected_not_raised(core, sig):
    """Each of these used to raise TypeError out of the auth check."""
    ts_hex, _ = _token(PASSWORD, int(time.time()))
    assert core._verify_auth_token(f"{ts_hex}.{sig}") is False


def test_expired_token_is_still_rejected(core):
    ts_hex, sig = _token(PASSWORD, int(time.time()) - 10 * 86400)
    assert core._verify_auth_token(f"{ts_hex}.{sig}") is False


# --- the /preview directory token -------------------------------------------


@pytest.fixture
def files_api(monkeypatch, tmp_path):
    from channel.web.api import files
    from channel.web.core import _common

    monkeypatch.setattr(_common, "_get_preview_secret", lambda: PREVIEW_SECRET)
    monkeypatch.setattr(files, "_get_preview_secret", lambda: PREVIEW_SECRET)
    return files


def _dir_token(real: str) -> str:
    body = base64.urlsafe_b64encode(real.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(PREVIEW_SECRET, real.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"{body}.{sig}"


def test_valid_preview_token_is_accepted(files_api, tmp_path):
    real = str(tmp_path)
    assert files_api._decode_dir_token(_dir_token(real)) == real


@pytest.mark.parametrize("sig", ["\u00e9" * 16, "\u4e2d\u6587" * 4, "\ud800", "z" * 15, "z" * 17])
def test_malformed_preview_signature_raises_value_error(files_api, tmp_path, sig):
    """A bad preview signature used to be a TypeError; it must be a ValueError."""
    real = str(tmp_path)
    body = base64.urlsafe_b64encode(real.encode("utf-8")).decode("ascii").rstrip("=")
    with pytest.raises(ValueError):
        files_api._decode_dir_token(f"{body}.{sig}")
