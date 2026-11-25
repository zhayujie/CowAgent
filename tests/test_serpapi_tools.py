"""Offline contract tests for the SerpApi backends behind web_search and web_fetch."""

import io
import json
import logging
import os
import socket
from http import client
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, quote_plus, urlsplit

import pytest
import requests
from urllib3 import connection
from urllib3.util import connection as urllib3_tcp

from agent.tools.utils.truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES
from agent.tools.web_fetch import web_fetch as fetch
from agent.tools.web_search import web_search as search
from channel.web.api import models


KEY = "fixture+secret/not-a-real-key"
URL = "https://93.184.216.34/article"


@pytest.fixture
def cfg(monkeypatch):
    config = {"tools": {"web_fetch": {"provider": "serpapi"}, "web_search": {}}}
    for module in (search, fetch, models):
        monkeypatch.setattr(module, "conf", lambda: config)
    monkeypatch.setattr("models.cowagent_provider.resolve_cowagent_credentials", lambda: ("", ""))
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=AssertionError("unexpected DNS lookup")))
    with patch.dict(os.environ, {"SERPAPI_API_KEY": KEY, "WEB_SECURITY_SSRF_PROTECTION": "true"}, clear=True):
        yield config


@pytest.fixture
def http(monkeypatch):
    wire = Mock()

    def connect(conn):
        wire.connect(conn.host, conn.port, conn._tunnel_host, conn.ca_certs, conn.timeout)
        conn.sock = wire
        conn.is_verified = True

    monkeypatch.setattr(connection.HTTPSConnection, "connect", connect)

    def respond(payload=None, status=200, raw=None, headers=b"", header_delay=0):
        body = raw if raw is not None else json.dumps(payload).encode()
        reply = f"HTTP/1.1 {status} Test\r\nContent-Length: {len(body)}\r\n".encode() + headers + b"\r\n" + body

        def makefile(*args):
            if header_delay and header_delay > wire.settimeout.call_args.args[0]:
                raise socket.timeout("response not ready")
            return io.BytesIO(reply)

        wire.makefile.side_effect = makefile
        return wire

    return respond


def request_params(wire, timeout):
    wire.connect.assert_called_once()
    host, _, _, _, actual_timeout = wire.connect.call_args.args
    assert (host, actual_timeout) == ("serpapi.com", timeout)
    wire.sendall.assert_called_once()
    request_line = wire.sendall.call_args.args[0].split(b"\r\n", 1)[0].decode()
    method, path, _ = request_line.split()
    assert method == "GET"
    assert urlsplit(path).path == "/search.json"
    wire.close.assert_called()
    return parse_qs(urlsplit(path).query)


def run_search(count=10):
    return search.WebSearch().execute({"provider": "serpapi", "query": "tea & coffee", "count": count})


def run_fetch(url=URL):
    return fetch.WebFetch().execute({"url": url})


@pytest.mark.parametrize("count,expected", [(2, 2), (50, 10)])
def test_one_google_page(cfg, http, count, expected):
    cfg["tools"]["web_search"]["serpapi_api_key"] = " saved-key "
    row = {"title": "Tea", "link": URL, "snippet": "Text", "date": "yesterday", "source": "Site"}
    conn = http({"organic_results": [None, {"link": "javascript:void(0)"}] + [row] * 12,
                 "ads": [{"title": "Ad"}], "serpapi_pagination": {"next": "not followed"}})
    result = run_search(count)
    assert result.status == "success"
    assert result.result == {
        "query": "tea & coffee", "backend": "serpapi", "total": expected, "count": expected,
        "results": [{"title": "Tea", "url": URL, "snippet": "Text",
                     "datePublished": "yesterday", "siteName": "Site"}] * expected,
    }
    assert request_params(conn, search.DEFAULT_TIMEOUT) == {
        "engine": ["google"], "api_key": ["saved-key"], "q": ["tea & coffee"],
    }
    conn.settimeout.assert_called_with(search.DEFAULT_TIMEOUT)


def test_extract_markdown_contract(cfg, http):
    # Allow the provider its 30s page fetch plus time to return the Markdown.
    conn = http({"markdown": "# Tea\n\n* Coffee", "page_information": {"title": "Drinks"}}, header_delay=33)
    result = run_fetch()
    assert result.status == "success"
    assert result.result == "Title: Drinks\n\nContent:\n# Tea\n\n* Coffee"
    assert request_params(conn, fetch.DEFAULT_TIMEOUT) == {
        "engine": ["extract"], "api_key": [KEY], "url": [URL],
    }


def test_extract_rejects_blocked_final_url(cfg, http):
    http({"markdown": "redirected", "page_information": {"final_url": "http://127.0.0.1/"}})
    result = run_fetch()
    assert result.status == "error" and "redirected" not in result.result


def test_existing_routes_win(cfg, http, monkeypatch):
    del cfg["tools"]["web_fetch"]["provider"]
    cfg["tools"]["web_search"]["keenable_anonymous"] = True
    monkeypatch.setattr(fetch.WebFetch, "_fetch_webpage", lambda self, url: "direct")
    monkeypatch.setattr(fetch.WebFetch, "_fetch_document", lambda self, url: "document")
    conn = http({})
    assert search.WebSearch()._resolve_provider(None) != "serpapi"
    assert search.WebSearch()._resolve_provider("serpapi") == "serpapi"
    assert run_fetch() == "direct"
    cfg["tools"]["web_fetch"]["provider"] = "serpapi"
    assert run_fetch(URL + ".pdf") == "document"
    conn.connect.assert_not_called()


def test_missing_key_and_blocked_urls_are_local(cfg, http, monkeypatch):
    conn = http({})
    for url in ("file:///etc/hosts", "http://127.0.0.1/", "http://169.254.169.254/"):
        assert run_fetch(url).status == "error"
    monkeypatch.delenv("SERPAPI_API_KEY")
    assert "serpapi" not in search.configured_providers()
    result = run_fetch()
    assert result.status == "error" and "SERPAPI_API_KEY" in result.result
    conn.connect.assert_not_called()


def test_settings_save_mask_and_disable(cfg, monkeypatch):
    handler = models.ModelsHandler()
    write = Mock()
    monkeypatch.setattr(handler, "_read_file_config", lambda: {})
    monkeypatch.setattr(handler, "_write_file_config", write)
    saved = KEY + "-saved"
    reply = handler._handle_set_search_credential({"provider": "serpapi", "api_key": saved})
    assert json.loads(reply)["status"] == "success"
    assert write.call_args.args[0]["tools"]["web_search"]["serpapi_api_key"] == saved
    assert search._get_api_key("serpapi") == saved
    entry = next(p for p in handler._search_capability(cfg)["providers"] if p["id"] == "serpapi")
    assert entry["configured"] and entry["needs_dedicated_key"] and entry["api_key_masked"]
    assert saved not in str(entry) + reply
    cfg["tools"]["web_search"]["disabled_providers"] = ["serpapi"]
    assert "serpapi" not in search.configured_providers()


@pytest.mark.parametrize("run", [run_search, run_fetch])
@pytest.mark.parametrize("payload,status,raw", [
    (None, 200, b"<not JSON>"), ([], 200, None), ({}, 200, None),
    ({"error": KEY}, 200, None), ({"search_metadata": {"status": "Processing"}}, 200, None),
    (None, 302, None), ({"error": KEY}, 401, None), ({"error": KEY}, 429, None),
])
def test_failures_never_echo_key(cfg, http, run, payload, status, raw, caplog, capsys):
    conn = http(payload, status, raw)
    result = run()
    assert result.status == "error"
    assert KEY not in result.result + caplog.text + capsys.readouterr().out
    conn.sendall.assert_called_once()


@pytest.mark.parametrize("run", [run_search, run_fetch])
def test_connection_exception_is_sanitized(cfg, http, run, caplog):
    conn = http()
    conn.makefile.side_effect = OSError("failed: /search.json?api_key=" + quote_plus(KEY))
    result = run()
    assert result.status == "error" and quote_plus(KEY) not in result.result + caplog.text
    conn.close.assert_called()


def test_extract_timeout_does_not_retry(cfg, http):
    conn = http({"markdown": "too late"}, header_delay=36)
    result = run_fetch()
    assert result.status == "error" and "timed out after 35s" in result.result and KEY not in result.result
    conn.sendall.assert_called_once()


@pytest.mark.parametrize("bypass", [False, True])
def test_requests_proxy_ca_and_debug_redaction(cfg, http, monkeypatch, tmp_path, capsys, caplog, bypass):
    ca_bundle = tmp_path / "custom-ca.pem"
    ca_bundle.touch()  # TLS is stubbed; inspect the actual connection's selected CA path.
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("NO_PROXY", "serpapi.com" if bypass else "")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(ca_bundle))
    monkeypatch.setattr(client.HTTPConnection, "debuglevel", 1)
    caplog.set_level(logging.DEBUG, logger="urllib3.connectionpool")
    wire = http({"organic_results": []})
    result = run_search()
    assert result.status == "success"
    host, port, tunnel, ca, _ = wire.connect.call_args.args
    assert (host, port) == (("serpapi.com", 443) if bypass else ("proxy.invalid", 3128))
    assert tunnel == (None if bypass else "serpapi.com")
    assert ca == str(ca_bundle)
    assert quote_plus(KEY).encode() in wire.sendall.call_args.args[0]
    assert "GET /search.json?" in caplog.text
    captured = capsys.readouterr()
    for secret in (KEY, quote_plus(KEY)):
        assert secret not in captured.out + captured.err + caplog.text


def test_key_is_not_attached_to_unrelated_requests(cfg, http):
    wire = http({"organic_results": []})
    assert run_search().status == "success"
    with requests.get("https://unrelated.invalid/search.json?q=other", timeout=1) as response:
        assert response.status_code == 200
    other_request = wire.sendall.call_args.args[0]
    assert b"GET /search.json?q=other HTTP/" in other_request and b"api_key=" not in other_request


def test_uses_cowagent_connection_deadline(cfg, monkeypatch):
    from common import connect_deadline

    lookup = Mock(side_effect=socket.gaierror("fixture lookup failure"))
    monkeypatch.setattr(connect_deadline, "_lookup", lookup)
    monkeypatch.setattr(urllib3_tcp, "create_connection", connect_deadline.create_connection)
    result = run_fetch()
    assert result.status == "error"
    lookup.assert_called_once()
    host, port, _, seconds = lookup.call_args.args
    assert (host, port, seconds) == ("serpapi.com", 443, connect_deadline.CONNECT_BUDGET_SECONDS)


def test_redirect_with_location_is_not_followed(cfg, http):
    wire = http(status=302, headers=b"Location: https://other.invalid/\r\n")
    result = run_search()
    assert result.status == "error" and "302" in result.result
    wire.sendall.assert_called_once()


def test_google_fully_empty_response_is_a_success(cfg, http):
    http({
        "search_metadata": {"status": "Success"},
        "search_information": {"organic_results_state": "Fully empty"},
        "error": "Google hasn't returned any results for this query.",
    })
    result = run_search()
    assert result.status == "success"
    assert result.result == {
        "query": "tea & coffee", "backend": "serpapi", "total": 0, "count": 0, "results": [],
    }


@pytest.mark.parametrize("run,fields", [
    (run_search, {"search_metadata": {"status": "Error"}}),
    (run_search, {"search_metadata": None}),
    (run_search, {"search_information": {}}),
    (run_search, {"organic_results": [{"link": URL}]}),
    (run_fetch, {"markdown": "This is not a successful extraction."}),
])
def test_only_a_successful_empty_google_search_can_carry_an_error(cfg, http, run, fields):
    http({"search_metadata": {"status": "Success"}, "search_information": {"organic_results_state": "Fully empty"},
          "error": KEY, **fields})
    result = run()
    assert result.status == "error" and KEY not in result.result


def test_search_rejects_malformed_results(cfg, http):
    http({"organic_results": {}})
    assert run_search().status == "error"


@pytest.mark.parametrize("markdown", [None, {}, "  "])
def test_extract_rejects_missing_or_malformed_markdown(cfg, http, markdown):
    http({"markdown": markdown})
    assert run_fetch().status == "error"


def test_redacts_echoes_even_on_success(cfg, http):
    echo = KEY + " " + quote_plus(KEY)
    http({"organic_results": [{"link": URL, "snippet": echo}]})
    results = run_search().result["results"]
    http({"markdown": echo})
    result = run_fetch()
    assert result.status == "success" and result.result.startswith("Title: Untitled\n")
    for value in (KEY, quote_plus(KEY)):
        assert value not in str(results) + result.result


def test_fetch_download_and_output_limits(cfg, http, monkeypatch):
    http({"markdown": "line\n" * DEFAULT_MAX_LINES + "last-line"})
    result = run_fetch()
    assert result.status == "success" and "truncated" in result.result.lower()
    assert "last-line" not in result.result and len(result.result.splitlines()) <= DEFAULT_MAX_LINES
    http({"markdown": "界" * DEFAULT_MAX_BYTES})
    result = run_fetch()
    assert result.status == "success" and len(result.result.encode()) <= DEFAULT_MAX_BYTES
    assert "界" in result.result and "truncated" in result.result.lower()
    monkeypatch.setattr(fetch, "MAX_FILE_SIZE", 32)
    http({"markdown": "x" * 100})
    assert run_fetch().status == "error"
