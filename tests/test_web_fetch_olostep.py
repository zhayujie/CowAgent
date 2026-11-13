"""Olostep backend for the web_fetch tool.

Covers provider selection (tools.web_fetch.provider: "olostep" opt-in),
key resolution (the web_search Olostep key -> env), the Markdown response
mapping, and the HTTP error mapping. No real network is used:
requests.post and the SSRF guard are stubbed throughout.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools.web_fetch import web_fetch as web_fetch_module
from agent.tools.web_fetch.web_fetch import WebFetch


def _fake_response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    body = payload if payload is not None else {}
    resp.json = lambda: body
    resp.text = json.dumps(body)
    resp.headers = {}
    return resp


def _conf(**kwargs):
    """Build a conf() stand-in returning the given top-level values."""
    return lambda: dict(kwargs)


def _scrape_payload(markdown, title=None):
    """An Olostep /v1/scrapes response body in the documented shape."""
    page_metadata = {"status_code": 200}
    if title is not None:
        page_metadata["title"] = title
    return {
        "id": "scrape_test",
        "object": "scrape",
        "url_to_scrape": "https://example.com/article",
        "result": {"markdown_content": markdown, "page_metadata": page_metadata},
    }


class TestOlostepProviderSelection:
    def test_olostep_provider_opt_in(self):
        cfg = {"tools": {"web_fetch": {"provider": "olostep"}}}
        with patch.object(web_fetch_module, "conf", lambda: cfg):
            assert web_fetch_module._fetch_provider() == "olostep"

    def test_unknown_provider_lists_olostep(self):
        cfg = {"tools": {"web_fetch": {"provider": "scrape"}}}
        with patch.object(web_fetch_module, "conf", lambda: cfg):
            with pytest.raises(ValueError, match="olostep"):
                web_fetch_module._fetch_provider()


class TestOlostepKeyResolution:
    def test_web_search_key_is_reused(self):
        cfg = {"tools": {"web_search": {"olostep_api_key": "search-key"}}}
        with patch.object(web_fetch_module, "conf", lambda: cfg), \
                patch.dict(os.environ, {"OLOSTEP_API_KEY": "env-key"}):
            assert web_fetch_module._olostep_api_key() == "search-key"

    def test_env_fallback(self):
        with patch.object(web_fetch_module, "conf", _conf()), \
                patch.dict(os.environ, {"OLOSTEP_API_KEY": "env-key"}):
            assert web_fetch_module._olostep_api_key() == "env-key"

    def test_no_key_anywhere(self):
        with patch.object(web_fetch_module, "conf", _conf()), \
                patch.dict(os.environ, {"OLOSTEP_API_KEY": ""}):
            assert web_fetch_module._olostep_api_key() == ""


def _olostep_execute(url="https://example.com/article", payload=None, status=200):
    """Run WebFetch.execute against the olostep backend with stubs."""
    full_cfg = {
        "tools": {
            "web_fetch": {"provider": "olostep"},
            "web_search": {"olostep_api_key": "test-key-123"},
        },
    }
    tool = WebFetch()
    with patch.object(web_fetch_module, "conf", lambda: full_cfg), \
            patch.object(web_fetch_module, "validate_url_safe", return_value=None), \
            patch.object(web_fetch_module.requests, "post",
                         return_value=_fake_response(status, payload)) as mock_post:
        result = tool.execute({"url": url})
    return result, mock_post


class TestOlostepFetchBackend:
    def test_success_returns_title_and_markdown(self):
        payload = _scrape_payload("# Example article\n\nBody text.", title="Example article")
        result, mock_post = _olostep_execute(payload=payload)
        assert result.status == "success"
        assert result.result == "Title: Example article\n\nContent:\n# Example article\n\nBody text."
        assert mock_post.call_args[0][0] == "https://api.olostep.com/v1/scrapes"
        assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer test-key-123"
        assert mock_post.call_args[1]["json"] == {
            "url_to_scrape": "https://example.com/article",
            "formats": ["markdown"],
        }
        assert mock_post.call_args[1]["timeout"] == web_fetch_module.OLOSTEP_TIMEOUT

    def test_missing_title_falls_back_to_untitled(self):
        result, _ = _olostep_execute(payload=_scrape_payload("Body text."))
        assert result.status == "success"
        assert result.result.startswith("Title: Untitled\n\n")

    def test_missing_key_fails_with_setup_hint(self):
        cfg = {"tools": {"web_fetch": {"provider": "olostep"}}}
        tool = WebFetch()
        with patch.object(web_fetch_module, "conf", lambda: cfg), \
                patch.object(web_fetch_module, "validate_url_safe", return_value=None), \
                patch.dict(os.environ, {"OLOSTEP_API_KEY": ""}), \
                patch.object(web_fetch_module.requests, "post") as mock_post:
            result = tool.execute({"url": "https://example.com/article"})
        assert result.status == "error"
        assert "olostep_api_key" in result.result
        assert "OLOSTEP_API_KEY" in result.result
        mock_post.assert_not_called()

    def test_ssrf_guard_still_applies(self):
        """The URL safety check runs before the backend dispatch, so a
        private URL never reaches Olostep's API either."""
        cfg = {"tools": {"web_fetch": {"provider": "olostep"}, "web_search": {"olostep_api_key": "k"}}}
        tool = WebFetch()
        with patch.object(web_fetch_module, "conf", lambda: cfg), \
                patch.object(web_fetch_module, "validate_url_safe",
                             side_effect=ValueError("URL resolves to a private address")), \
                patch.object(web_fetch_module.requests, "post") as mock_post:
            result = tool.execute({"url": "http://169.254.169.254/"})
        assert result.status == "error"
        assert "private" in result.result
        mock_post.assert_not_called()

    @pytest.mark.parametrize("status_code,fragment", [
        (401, "Invalid Olostep API key"),
        (402, "out of credits"),
        (429, "rate limit reached"),
        (504, "could not finish scraping in time"),
        (500, "HTTP 500"),
    ])
    def test_error_status_mapping(self, status_code, fragment):
        result, _ = _olostep_execute(status=status_code)
        assert result.status == "error"
        assert fragment in result.result

    def test_empty_content_is_an_error(self):
        result, _ = _olostep_execute(payload=_scrape_payload("   ", title="T"))
        assert result.status == "error"
        assert "no content" in result.result

    def test_document_urls_stay_local(self):
        tool = WebFetch()
        cfg = {"tools": {"web_fetch": {"provider": "olostep"}, "web_search": {"olostep_api_key": "k"}}}
        with patch.object(web_fetch_module, "conf", lambda: cfg), \
                patch.object(web_fetch_module, "validate_url_safe", return_value=None), \
                patch.object(WebFetch, "_fetch_document", return_value="local") as mock_doc, \
                patch.object(web_fetch_module.requests, "post") as mock_post:
            assert tool.execute({"url": "https://example.com/report.pdf"}) == "local"
        mock_doc.assert_called_once()
        mock_post.assert_not_called()
