# encoding:utf-8
"""A web page on another site must not be able to drive the console.

Without a password, a page the user happens to visit could POST a message to
the agent on localhost (no preflight for a text/plain body) or rebind its own
domain to 127.0.0.1 and read the console as same-origin.
"""

import pytest

from channel.web.core.request_guard import GuardPolicy, guard_requests, refusal

OPEN = GuardPolicy(password_set=False)
LOCKED = GuardPolicy(password_set=True)


def _env(method="POST", path="/message", host="127.0.0.1:9899", **headers):
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": host, "REMOTE_ADDR": "127.0.0.1"}
    env.update({f"HTTP_{k.upper()}": v for k, v in headers.items()})
    return env


# --- cross-site writes -------------------------------------------------------


@pytest.mark.parametrize("policy", [OPEN, LOCKED])
def test_cross_site_post_is_refused(policy):
    env = _env(sec_fetch_site="cross-site", origin="https://evil.example")
    assert refusal(env, policy)


def test_same_site_post_is_refused():
    # Another port on the same host is same-site, and SameSite=Lax cookies go along.
    env = _env(sec_fetch_site="same-site", origin="http://127.0.0.1:3000")
    assert refusal(env, LOCKED)


def test_same_origin_post_passes():
    assert refusal(_env(sec_fetch_site="same-origin", origin="http://127.0.0.1:9899"), OPEN) is None


def test_native_client_without_browser_headers_passes():
    assert refusal(_env(), OPEN) is None


def test_reads_are_not_checked_for_origin():
    assert refusal(_env(method="GET", sec_fetch_site="cross-site"), OPEN) is None


def test_old_browser_with_mismatched_origin_is_refused():
    assert refusal(_env(origin="https://evil.example"), OPEN)


def test_old_browser_with_matching_origin_passes():
    assert refusal(_env(origin="http://127.0.0.1:9899"), OPEN) is None


def test_origin_matching_the_proxied_host_passes():
    env = _env(host="127.0.0.1:9899", origin="https://cow.example.com", x_forwarded_host="cow.example.com")
    assert refusal(env, LOCKED) is None


def test_null_origin_is_refused():
    # Sandboxed iframes on any site send Origin: null.
    assert refusal(_env(origin="null"), OPEN)


def test_desktop_shell_token_lets_its_cross_site_writes_through():
    env = _env(sec_fetch_site="cross-site")
    assert refusal(env, OPEN, desktop_token_ok=True) is None


def test_listed_origin_passes():
    policy = GuardPolicy(password_set=True, allowed_origins=frozenset({"https://dash.example.com"}))
    env = _env(sec_fetch_site="cross-site", origin="https://dash.example.com")
    assert refusal(env, policy) is None


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/share/abcdefghijklmnop/api/chat"])
def test_paths_with_their_own_policy_are_left_alone(path):
    env = _env(path=path, sec_fetch_site="cross-site", origin="https://site.example")
    assert refusal(env, LOCKED) is None


# --- host names without a password -------------------------------------------


LISTED = GuardPolicy(password_set=False, allowed_hosts=frozenset({"cow.example.com"}))


@pytest.mark.parametrize("host", ["cow.company.com", "nas:9899", "my-mac.local", "cow-agent"])
@pytest.mark.parametrize("path", ["/", "/v1/chat/completions", "/api/health"])
def test_any_host_passes_without_password_by_default(host, path):
    assert refusal(_env(method="GET", host=host, path=path), OPEN) is None


@pytest.mark.parametrize("host", [
    "127.0.0.1:9899", "localhost:9899", "[::1]:9899", "192.168.1.20:9899",
    "app.localhost", "", "cow.example.com",
])
def test_local_and_listed_names_pass_once_hosts_are_listed(host):
    assert refusal(_env(method="GET", host=host), LISTED) is None


@pytest.mark.parametrize("host", ["attacker.example:9899", "nas", "my-mac.local"])
def test_other_names_are_refused_once_hosts_are_listed(host):
    assert refusal(_env(method="GET", host=host), LISTED)


def test_any_host_passes_with_password():
    policy = GuardPolicy(password_set=True, allowed_hosts=frozenset({"cow.example.com"}))
    assert refusal(_env(method="GET", host="other.example.com"), policy) is None


def test_display_address_and_listed_hosts_come_from_config(monkeypatch):
    from channel.web.core import request_guard
    from config import conf

    monkeypatch.setitem(conf(), "web_password", "")
    monkeypatch.setitem(conf(), "web_public_url", "https://cow.company.com/")
    monkeypatch.setitem(conf(), "web_allowed_hosts", ["NAS"])
    policy = request_guard.current_policy()
    assert refusal(_env(method="GET", host="cow.company.com"), policy) is None
    assert refusal(_env(method="GET", host="nas:9899"), policy) is None
    assert refusal(_env(method="GET", host="other.company.com"), policy)


def test_display_address_alone_does_not_turn_the_host_check_on(monkeypatch):
    from channel.web.core import request_guard
    from config import conf

    monkeypatch.setitem(conf(), "web_password", "")
    monkeypatch.setitem(conf(), "web_public_url", "https://cow.company.com/")
    monkeypatch.setitem(conf(), "web_allowed_hosts", [])
    policy = request_guard.current_policy()
    assert refusal(_env(method="GET", host="nas:9899"), policy) is None


def test_host_check_is_left_to_an_authenticating_proxy():
    policy = GuardPolicy(password_set=False, behind_auth_proxy=True, allowed_hosts=frozenset({"x"}))
    assert refusal(_env(method="GET", host="slug.example.app"), policy) is None


# --- the middleware ----------------------------------------------------------


def _call(app, env):
    seen = {}

    def start_response(status, headers):
        seen["status"] = status

    body = b"".join(app(env, start_response))
    return seen["status"], body


@pytest.fixture
def open_console(monkeypatch):
    from channel.web.core import request_guard

    monkeypatch.setattr(request_guard, "current_policy", lambda: OPEN)

    def inner(environ, start_response):
        start_response("200 OK", [])
        return [b"ok"]

    return guard_requests(inner)


def test_middleware_refuses_with_403(open_console):
    status, body = _call(open_console, _env(sec_fetch_site="cross-site", origin="https://evil.example"))
    assert status.startswith("403")
    assert b"web_allowed_origins" in body


def test_middleware_explains_a_refused_host_to_a_browser(open_console, monkeypatch):
    from channel.web.core import request_guard

    monkeypatch.setattr(request_guard, "current_policy", lambda: LISTED)
    env = _env(method="GET", path="/", host="cow.company.com", accept="text/html,*/*")
    status, body = _call(open_console, env)
    assert status.startswith("403")
    assert b"web_password" in body and b'{&quot;web_allowed_hosts&quot;: [&quot;cow.company.com&quot;]}' in body


def test_middleware_passes_same_origin(open_console):
    assert _call(open_console, _env(sec_fetch_site="same-origin")) == ("200 OK", b"ok")


def test_middleware_honours_the_desktop_token(open_console, monkeypatch):
    monkeypatch.setenv("COW_DESKTOP_TOKEN", "shell-secret")
    env = _env(sec_fetch_site="cross-site", x_cow_desktop_token="shell-secret")
    assert _call(open_console, env)[0] == "200 OK"
    env = _env(sec_fetch_site="cross-site", x_cow_desktop_token="guess")
    assert _call(open_console, env)[0].startswith("403")
