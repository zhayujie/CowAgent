# encoding:utf-8
"""A password-less console must refuse cross-site state-changing requests.

Without a ``web_password`` any page the operator has open could otherwise POST
to the console and drive the full-access agent. Reads, plain local callers and
the desktop shell (which proves itself with its spawn token) keep working.
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


class _HTTPError(Exception):
    def __init__(self, status, headers=None, data=""):
        super().__init__(status)
        self.status = status


class _FakeWeb:
    HTTPError = _HTTPError

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


def _patched(env, password="", desktop_token=""):
    return (
        patch.object(common, "web", _FakeWeb(env)),
        patch.object(common, "conf", lambda: {"web_password": password}),
        patch.dict("os.environ", {"COW_DESKTOP_TOKEN": desktop_token}),
    )


def _auth(env, password="", desktop_token=""):
    """Run ``_check_auth`` against a fabricated request and config."""
    p_web, p_conf, p_env = _patched(env, password, desktop_token)
    with p_web, p_conf, p_env:
        return common._check_auth()


# --- cross-site writes on a password-less console ---------------------------


def test_cross_origin_post_is_refused_when_no_password():
    assert _auth(_env("POST", origin="https://example.com")) is False


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_cross_origin_non_get_methods_are_refused(method):
    assert _auth(_env(method, origin="http://attacker.test")) is False


def test_null_origin_without_the_desktop_token_is_refused():
    # A sandboxed iframe or data: URL page also sends Origin: null.
    assert _auth(_env("POST", origin="null")) is False


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_fetch_metadata_marking_another_site_is_refused(site):
    env = _env("POST", origin="http://127.0.0.1:9899", extra={"HTTP_SEC_FETCH_SITE": site})
    assert _auth(env) is False


def test_another_port_on_the_same_host_is_refused():
    assert _auth(_env("POST", origin="http://127.0.0.1:5173")) is False


def test_refused_write_gets_403_not_the_login_401():
    p_web, p_conf, p_env = _patched(_env("POST", origin="https://example.com"))
    with p_web, p_conf, p_env, pytest.raises(_HTTPError) as exc:
        common._require_auth()
    assert exc.value.status.startswith("403")


# --- legitimate callers keep working ----------------------------------------


def test_same_origin_post_is_allowed():
    assert _auth(_env("POST", origin="http://127.0.0.1:9899")) is True


def test_fetch_metadata_same_origin_is_allowed_behind_a_proxy():
    # A reverse proxy may rewrite Host, but the browser still says same-origin.
    env = _env("POST", origin="https://cow.example.com", host="127.0.0.1:9899",
               extra={"HTTP_SEC_FETCH_SITE": "same-origin"})
    assert _auth(env) is True


def test_forwarded_host_matching_the_origin_is_allowed():
    env = _env("POST", origin="https://cow.example.com", host="127.0.0.1:9899",
               extra={"HTTP_X_FORWARDED_HOST": "cow.example.com, inner"})
    assert _auth(env) is True


def test_post_without_origin_is_allowed_for_local_callers():
    # curl, local scripts and native clients send no Origin header.
    assert _auth(_env("POST")) is True


def test_desktop_renderer_with_its_token_is_allowed():
    # The Electron renderer runs from file://, which arrives as Origin: null.
    env = _env("POST", origin="null",
               extra={"HTTP_SEC_FETCH_SITE": "cross-site", "HTTP_X_COW_DESKTOP_TOKEN": "tok"})
    assert _auth(env, desktop_token="tok") is True


def test_a_wrong_desktop_token_is_refused():
    env = _env("POST", origin="null", extra={"HTTP_X_COW_DESKTOP_TOKEN": "guess"})
    assert _auth(env, desktop_token="tok") is False


def test_cross_origin_get_is_allowed():
    assert _auth(_env("GET", origin="https://example.com")) is True


# --- a configured password is unaffected ------------------------------------


def test_password_set_still_requires_a_credential():
    assert _auth(_env("POST", origin="http://127.0.0.1:9899"), password="s3cret") is False


def test_password_set_rejects_cross_origin_write():
    assert _auth(_env("POST", origin="https://example.com"), password="s3cret") is False
