"""HTTPS and reverse-proxy plumbing for the web console.

Behind nginx the console only sees the proxy's internal hop, so the app
would build http:// URLs and log the proxy's IP unless the X-Forwarded-*
headers are applied. And a typo in the TLS cert path must fail startup
loudly, never silently serve plain HTTP instead.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel.web.core.proxy import (  # noqa: E402
    TrustProxyMiddleware,
    build_ssl_adapter,
    resolve_tls_config,
)


def _environ(**headers):
    env = {"wsgi.url_scheme": "http", "HTTP_HOST": "127.0.0.1:9899", "REMOTE_ADDR": "127.0.0.1"}
    env.update(headers)
    return env


def _run(app_env):
    seen = {}

    def app(environ, start_response):
        seen.update(environ)
        return ["ok"]

    TrustProxyMiddleware(app)(app_env, lambda *a: None)
    return seen


def test_forwarded_headers_rewrite_scheme_host_and_client_ip():
    seen = _run(_environ(
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_HOST="cow.example.com",
        HTTP_X_FORWARDED_FOR="203.0.113.7",
    ))
    assert seen["wsgi.url_scheme"] == "https"
    assert seen["HTTP_HOST"] == "cow.example.com"
    assert seen["REMOTE_ADDR"] == "203.0.113.7"


def test_no_headers_leaves_environ_untouched():
    seen = _run(_environ())
    assert seen["wsgi.url_scheme"] == "http"
    assert seen["HTTP_HOST"] == "127.0.0.1:9899"
    assert seen["REMOTE_ADDR"] == "127.0.0.1"


def test_partial_headers_only_rewrite_what_is_present():
    seen = _run(_environ(HTTP_X_FORWARDED_PROTO="https"))
    assert seen["wsgi.url_scheme"] == "https"
    assert seen["HTTP_HOST"] == "127.0.0.1:9899"
    assert seen["REMOTE_ADDR"] == "127.0.0.1"


def test_first_forwarded_value_wins_behind_chained_proxies():
    seen = _run(_environ(
        HTTP_X_FORWARDED_PROTO="https, http",
        HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
        HTTP_X_FORWARDED_HOST="cow.example.com, internal",
    ))
    assert seen["wsgi.url_scheme"] == "https"
    assert seen["REMOTE_ADDR"] == "203.0.113.7"
    assert seen["HTTP_HOST"] == "cow.example.com"


def test_tls_disabled_returns_no_paths():
    assert resolve_tls_config(False, "", "") == (None, None)
    # Stale paths must not matter while the feature is off.
    assert resolve_tls_config(False, "/nope/cert.pem", "/nope/key.pem") == (None, None)


def test_tls_enabled_without_certfile_fails_fast():
    with pytest.raises(ValueError, match="web_ssl_certfile"):
        resolve_tls_config(True, "", "/some/key.pem")


def test_tls_enabled_without_keyfile_fails_fast():
    with pytest.raises(ValueError, match="web_ssl_keyfile"):
        resolve_tls_config(True, "/some/cert.pem", "")


def test_tls_enabled_with_missing_files_fails_fast(tmp_path):
    missing = str(tmp_path / "cert.pem")
    with pytest.raises(ValueError, match="web_ssl_certfile"):
        resolve_tls_config(True, missing, missing)


def test_tls_enabled_with_real_files_returns_expanded_paths(tmp_path):
    cert = tmp_path / "fullchain.pem"
    key = tmp_path / "privkey.pem"
    cert.write_text("cert")
    key.write_text("key")
    got_cert, got_key = resolve_tls_config(True, str(cert), str(key))
    assert got_cert == str(cert)
    assert got_key == str(key)


def test_build_ssl_adapter_uses_cheroot_builtin_adapter(monkeypatch):
    made = {}

    class FakeAdapter:
        def __init__(self, certificate, private_key):
            made["certificate"] = certificate
            made["private_key"] = private_key

    cheroot = types.ModuleType("cheroot")
    ssl_pkg = types.ModuleType("cheroot.ssl")
    builtin = types.ModuleType("cheroot.ssl.builtin")
    builtin.BuiltinSSLAdapter = FakeAdapter
    monkeypatch.setitem(sys.modules, "cheroot", cheroot)
    monkeypatch.setitem(sys.modules, "cheroot.ssl", ssl_pkg)
    monkeypatch.setitem(sys.modules, "cheroot.ssl.builtin", builtin)

    adapter = build_ssl_adapter("/x/cert.pem", "/x/key.pem")
    assert isinstance(adapter, FakeAdapter)
    assert made == {"certificate": "/x/cert.pem", "private_key": "/x/key.pem"}


def test_build_ssl_adapter_without_cheroot_raises_clear_error(monkeypatch):
    monkeypatch.delitem(sys.modules, "cheroot", raising=False)
    monkeypatch.delitem(sys.modules, "cheroot.ssl", raising=False)
    monkeypatch.delitem(sys.modules, "cheroot.ssl.builtin", raising=False)
    # Make sure a real cheroot can't leak back in through the import system.
    monkeypatch.setitem(sys.modules, "cheroot", None)
    with pytest.raises(RuntimeError, match="cheroot"):
        build_ssl_adapter("/x/cert.pem", "/x/key.pem")
