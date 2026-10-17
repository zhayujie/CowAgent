"""DeepSeek Fetch backend for the web_fetch tool.

Covers provider selection (tools.web_fetch.provider: "direct" default,
"deepseek" opt-in), key resolution (dedicated key -> shared DeepSeek model
credential -> env), the Markdown response mapping, and the documented HTTP
and business-level error mapping. No real network is used: requests.post
and the SSRF guard are stubbed throughout.
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


class TestFetchProviderSelection:
    def test_default_provider_is_direct(self):
        with patch.object(web_fetch_module, "conf", _conf()):
            assert web_fetch_module._fetch_provider() == "direct"

    def test_deepseek_provider_opt_in(self):
        cfg = {"tools": {"web_fetch": {"provider": "deepseek"}}}
        with patch.object(web_fetch_module, "conf", lambda: cfg):
            assert web_fetch_module._fetch_provider() == "deepseek"

    def test_unknown_provider_fails_loudly(self):
        cfg = {"tools": {"web_fetch": {"provider": "scrape"}}}
        with patch.object(web_fetch_module, "conf", lambda: cfg):
            with pytest.raises(ValueError, match="direct.*deepseek"):
                web_fetch_module._fetch_provider()


class TestDeepSeekKeyResolution:
    def test_dedicated_key_wins(self):
        cfg = {
            "tools": {"web_fetch": {"deepseek_api_key": "fetch-key"}},
            "deepseek_api_key": "model-key",
        }
        with patch.object(web_fetch_module, "conf", lambda: cfg), \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            assert web_fetch_module._deepseek_api_key() == "fetch-key"

    def test_model_key_fallback(self):
        cfg = {"deepseek_api_key": "model-key"}
        with patch.object(web_fetch_module, "conf", lambda: cfg), \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            assert web_fetch_module._deepseek_api_key() == "model-key"

    def test_env_fallback(self):
        with patch.object(web_fetch_module, "conf", _conf()), \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            assert web_fetch_module._deepseek_api_key() == "env-key"

    def test_no_key_anywhere(self):
        with patch.object(web_fetch_module, "conf", _conf()), \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            assert web_fetch_module._deepseek_api_key() == ""


def _deepseek_execute(url="https://example.com/article", cfg=None, payload=None, status=200):
    """Run WebFetch.execute against the deepseek backend with stubs."""
    full_cfg = {
        "tools": {"web_fetch": {"provider": "deepseek", **(cfg or {})}},
        "deepseek_api_key": "test-key-123",
    }
    tool = WebFetch()
    with patch.object(web_fetch_module, "conf", lambda: full_cfg), \
            patch.object(web_fetch_module, "validate_url_safe", return_value=None), \
            patch.object(web_fetch_module.requests, "post",
                         return_value=_fake_response(status, payload)) as mock_post:
        result = tool.execute({"url": url})
    return result, mock_post


class TestDeepSeekFetchBackend:
    def test_success_returns_title_and_markdown(self):
        payload = {"title": "Example article", "content": "# Example article\n\nBody text."}
        result, mock_post = _deepseek_execute(payload=payload)
        assert result.status == "success"
        assert result.result == "Title: Example article\n\nContent:\n# Example article\n\nBody text."
        assert mock_post.call_args[0][0] == "https://api.deepseek.com/v1/tools/fetch"
        assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer test-key-123"
        assert mock_post.call_args[1]["json"] == {"url": "https://example.com/article"}

    def test_missing_key_fails_with_setup_hint(self):
        cfg = {"tools": {"web_fetch": {"provider": "deepseek"}}}
        tool = WebFetch()
        with patch.object(web_fetch_module, "conf", lambda: cfg), \
                patch.object(web_fetch_module, "validate_url_safe", return_value=None), \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            result = tool.execute({"url": "https://example.com/article"})
        assert result.status == "error"
        assert "deepseek_api_key" in result.result
        assert "DEEPSEEK_API_KEY" in result.result

    def test_ssrf_guard_still_applies(self):
        """The URL safety check runs before the backend dispatch, so a
        private URL never reaches DeepSeek's API either."""
        cfg = {"tools": {"web_fetch": {"provider": "deepseek"}}, "deepseek_api_key": "k"}
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
        (401, "Invalid DeepSeek API key"),
        (402, "insufficient balance"),
        (403, "security policy"),
        (404, "could not retrieve usable content"),
        (429, "rate limit reached"),
        (500, "HTTP 500"),
    ])
    def test_error_status_mapping(self, status_code, fragment):
        result, _ = _deepseek_execute(status=status_code)
        assert result.status == "error"
        assert fragment in result.result

    def test_business_error_envelope(self):
        payload = {"error": {"message": "rejected by security policy",
                             "type": "invalid_request_error", "param": None,
                             "code": "invalid_request_error"}}
        result, _ = _deepseek_execute(payload=payload)
        assert result.status == "error"
        assert "invalid_request_error" in result.result

    def test_empty_content_is_an_error(self):
        result, _ = _deepseek_execute(payload={"title": "T", "content": "   "})
        assert result.status == "error"
        assert "no content" in result.result
