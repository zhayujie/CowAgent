# encoding:utf-8
"""
Unit tests for per-gateway attribution headers in models/openai/openai_http_client.py.

Covers _resolve_attribution_headers():
  - OrcaRouter (api.orcarouter.ai) receives HTTP-Referer / X-Title, mirroring the
    existing OpenRouter entry
  - Bare / subdomain hosts of a documented gateway match
  - Non-gateway (user-configured custom proxy) hosts get no attribution headers,
    so app identity is not leaked to arbitrary endpoints
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.openai.openai_http_client import (  # noqa: E402
    _APP_REFERER,
    _APP_TITLE,
    _resolve_attribution_headers,
)


class TestResolveAttributionHeaders(unittest.TestCase):
    """_resolve_attribution_headers() host-suffix dispatch."""

    def test_orcarouter_main_host(self):
        headers = _resolve_attribution_headers(
            "https://api.orcarouter.ai/v1/chat/completions"
        )
        self.assertEqual(
            headers,
            {"HTTP-Referer": _APP_REFERER, "X-Title": _APP_TITLE},
        )

    def test_orcarouter_bare_host(self):
        self.assertEqual(
            _resolve_attribution_headers("https://orcarouter.ai/v1"),
            {"HTTP-Referer": _APP_REFERER, "X-Title": _APP_TITLE},
        )

    def test_orcarouter_subdomain(self):
        self.assertEqual(
            _resolve_attribution_headers("https://beta.orcarouter.ai/v1"),
            {"HTTP-Referer": _APP_REFERER, "X-Title": _APP_TITLE},
        )

    def test_openrouter_still_matches(self):
        """Guard the mirrored OpenRouter entry stays intact."""
        self.assertEqual(
            _resolve_attribution_headers("https://openrouter.ai/api/v1/chat/completions"),
            {"HTTP-Referer": _APP_REFERER, "X-Title": _APP_TITLE},
        )

    def test_vercel_gateway_still_matches(self):
        self.assertEqual(
            _resolve_attribution_headers("https://ai-gateway.vercel.sh/v1"),
            {"HTTP-Referer": _APP_REFERER, "X-Title": _APP_TITLE},
        )

    def test_non_gateway_host_gets_no_headers(self):
        """Attribution must not leak to a user's own custom proxy."""
        self.assertEqual(
            _resolve_attribution_headers("https://api.example.com/v1/chat/completions"),
            {},
        )

    def test_unparseable_url_safe(self):
        self.assertEqual(_resolve_attribution_headers("not a url"), {})


if __name__ == "__main__":
    unittest.main()
