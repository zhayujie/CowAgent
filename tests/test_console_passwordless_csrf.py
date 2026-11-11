# encoding:utf-8
"""A password-less console must refuse cross-origin state-changing requests.

With no ``web_password`` (the shipped default) ``_check_auth`` returned ``True``
unconditionally, so any page the operator had open could POST to loopback and
drive the full-access agent (or overwrite workspace files) with no credential.
``_check_auth`` now refuses a state-changing request that a browser is making
from another origin, while leaving reads, plain local callers and the desktop
shell working. These tests pin that boundary so the fail-open cannot come back.
"""

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Keep this unit test independent from the optional web.py dependency. The
# real package is preferred when present: a stub left in sys.modules stands in
# for it in every test that imports the web channel afterwards, and answers
# only for the attributes it happens to declare.
try:
    import web  # noqa: F401
except ImportError:
    web = types.ModuleType("web")
    web.ctx = types.SimpleNamespace(env={})
    web.cookies = lambda: {}
    web.HTTPError = type("HTTPError", (Exception,), {})
    sys.modules["web"] = web

from channel.web.core import _common as common  # noqa: E402

LOOPBACK = "127.0.0.1"


class _FakeWeb:
    def __init__(self, env):
        self.ctx = types.SimpleNamespace(env=env)

    def cookies(self):
        return {}


def _env(method="POST", origin=None, host=f"{LOOPBACK}:9899", extra=None):
    env = {"REQUEST_METHOD": method, "HTTP_HOST": host, "REMOTE_ADDR": LOOPBACK}
    if origin is not None:
        env["HTTP_ORIGIN"] = origin
    if extra:
        env.update(extra)
    return env


def _auth(env, password="", desktop_token=""):
    """Run ``_check_auth`` against a fabricated request and config."""
    with patch.object(common, "web", _FakeWeb(env)), \
            patch.object(common, "conf", lambda: {"web_password": password}), \
            patch.dict("os.environ", {"COW_DESKTOP_TOKEN": desktop_token}):
        return common._check_auth()


# --- the vulnerability: a cross-origin write on a password-less console -----


def test_cross_origin_post_is_refused_when_no_password():
    assert _auth(_env("POST", origin="https://example.com")) is False


def test_cross_origin_post_with_referer_only_is_refused():
    env = _env("POST", extra={"HTTP_REFERER": "https://evil.test/page"})
    assert _auth(env) is False


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_cross_origin_non_get_methods_are_refused(method):
    assert _auth(_env(method, origin="http://attacker.test")) is False


# --- legitimate callers must keep working ----------------------------------


def test_same_origin_post_is_allowed():
    env = _env("POST", origin="http://127.0.0.1:9899")
    assert _auth(env) is True


def test_post_without_origin_is_allowed_for_local_callers():
    # curl, a local script, the desktop shell's non-XHR calls: no Origin header.
    assert _auth(_env("POST")) is True


def test_desktop_file_origin_null_is_allowed():
    # The Electron renderer runs from file://, which arrives as Origin: null.
    assert _auth(_env("POST", origin="null")) is True


def test_cross_origin_desktop_request_with_token_is_allowed():
    assert _auth(
        _env("POST", origin="https://example.com",
             extra={"HTTP_X_COW_DESKTOP_TOKEN": "tok"}),
        desktop_token="tok",
    ) is True


def test_cross_origin_get_is_allowed():
    # Reads on a password-less console stay local-only and are not state-changing.
    assert _auth(_env("GET", origin="https://example.com")) is True


# --- a configured password is unaffected ------------------------------------


def test_password_set_still_requires_a_credential():
    assert _auth(_env("POST", origin="http://127.0.0.1:9899"), password="s3cret") is False


def test_password_set_rejects_cross_origin_write():
    assert _auth(_env("POST", origin="https://example.com"), password="s3cret") is False
