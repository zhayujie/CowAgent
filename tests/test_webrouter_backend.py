# encoding:utf-8
"""WebRouter backend for the web_search and web_fetch tools.

Covers the opt-in contract (tools.web_search.webrouter_enabled plus the
optional webrouter package), the arguments sent to WebRouter, the mapping of
its results into the unified output shape, error handling, the web_fetch
backend, and the console's save path. No real network is used: the
web_router module is replaced by a stub, since CI installs only
requirements.txt.
"""
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.web_fetch import web_fetch as web_fetch_module
from agent.tools.web_fetch.web_fetch import WebFetch
from agent.tools.web_search import WebSearch
from agent.tools.web_search import web_search as web_search_module

_ALL_SEARCH_ENV = (
    "BOCHA_API_KEY", "ZHIPUAI_API_KEY", "QIANFAN_API_KEY", "LINKAI_API_KEY", "DEEPSEEK_API_KEY",
    "ANYSEARCH_API_KEY", "SERPLY_API_KEY", "TAVILY_API_KEY", "OUTCRAWL_API_KEY", "FIRECRAWL_API_KEY",
    "CONTEXT_DEV_API_KEY", "SPECSTREAM_API_KEY", "OLOSTEP_API_KEY", "SEARCHAPI_API_KEY",
    "KEENABLE_API_KEY", "SEARXNG_URL",
)
_ENABLED = {"tools": {"web_search": {"webrouter_enabled": True}}}


def _stub_web_router(client):
    """A stand-in `web_router` module whose WebRouter() returns `client`."""
    module = types.ModuleType("web_router")
    module.WebRouter = MagicMock(return_value=client)
    return patch.dict(sys.modules, {"web_router": module})


def _result(title="T", url="https://example.com", description="snippet", content=None, published_date=None):
    return types.SimpleNamespace(
        title=title, url=url, description=description, content=content, published_date=published_date,
    )


class TestWebRouterOptIn(unittest.TestCase):
    """WebRouter is configured only when turned on and installed, and sits
    last in the fallback order so any provider the user paid for wins."""

    def _configured(self, cfg, installed=True):
        with patch.object(web_search_module, "conf", lambda: cfg), \
                patch.object(web_search_module, "webrouter_installed", return_value=installed), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            return web_search_module.configured_providers()

    def test_fresh_install_leaves_webrouter_unconfigured(self):
        self.assertEqual(self._configured({}), [])

    def test_opt_in_configures_webrouter(self):
        self.assertEqual(self._configured(_ENABLED), ["webrouter"])

    def test_opt_in_without_the_package_configures_nothing(self):
        self.assertEqual(self._configured(_ENABLED, installed=False), [])

    def test_string_false_stays_off(self):
        self.assertEqual(self._configured({"tools": {"web_search": {"webrouter_enabled": "false"}}}), [])

    def test_keyed_provider_wins_over_webrouter(self):
        cfg = {"tools": {"web_search": {"serply_api_key": "k", "webrouter_enabled": True}}}
        self.assertEqual(self._configured(cfg), ["serply", "webrouter"])

    def test_disabled_providers_skip_webrouter(self):
        cfg = {"tools": {"web_search": {"webrouter_enabled": True, "disabled_providers": ["webrouter"]}}}
        self.assertEqual(self._configured(cfg), [])


class TestWebRouterSearch(unittest.TestCase):
    def _search(self, client, **args):
        with patch.object(web_search_module, "conf", lambda: _ENABLED), \
                patch.object(web_search_module, "webrouter_installed", return_value=True), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}), \
                _stub_web_router(client):
            return WebSearch().execute({"query": "hangzhou weather", **args})

    def test_sends_count_recency_timeout_and_web_results_only(self):
        client = MagicMock()
        client.search.return_value = types.SimpleNamespace(results=[])
        self._search(client, count=5, freshness="oneWeek")
        client.search.assert_called_once_with(
            "hangzhou weather", max_results=5, recency="week",
            timeout=web_search_module.DEFAULT_TIMEOUT, data_apis=False,
        )

    def test_date_range_freshness_is_not_sent(self):
        client = MagicMock()
        client.search.return_value = types.SimpleNamespace(results=[])
        self._search(client, freshness="2025-01-01..2025-02-01")
        self.assertIsNone(client.search.call_args[1]["recency"])

    def test_maps_results_to_unified_shape(self):
        client = MagicMock()
        client.search.return_value = types.SimpleNamespace(results=[
            _result("A", "https://a.example", "first", published_date="2026-11-25T08:00:00"),
            _result("B", "https://b.example", None, content="x" * 900),
        ])
        result = self._search(client)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["backend"], "webrouter")
        self.assertEqual(result.result["count"], 2)
        first, second = result.result["results"]
        self.assertEqual(first, {
            "title": "A", "url": "https://a.example", "snippet": "first",
            "datePublished": "2026-11-25T08:00:00",
        })
        # No description: the page text is cut to snippet length.
        self.assertEqual(second["snippet"], "x" * 500)
        self.assertEqual(second["datePublished"], "")

    def test_failure_becomes_a_short_error_result(self):
        client = MagicMock()
        client.search.side_effect = RuntimeError("no backend in the chain could serve the request" + "x" * 5000)
        result = self._search(client)
        self.assertEqual(result.status, "error")
        self.assertIn("no backend", result.result)
        self.assertLess(len(result.result), 600)


class TestWebRouterFetch(unittest.TestCase):
    _CFG = {"tools": {"web_fetch": {"provider": "webrouter"}}}

    def _fetch(self, client, url="https://example.com/article", installed=True):
        with patch.object(web_fetch_module, "conf", lambda: self._CFG), \
                patch.object(web_fetch_module, "validate_url_safe", return_value=None), \
                patch.object(web_search_module, "webrouter_installed", return_value=installed), \
                _stub_web_router(client):
            return WebFetch().execute({"url": url})

    def test_provider_opt_in(self):
        with patch.object(web_fetch_module, "conf", lambda: self._CFG):
            self.assertEqual(web_fetch_module._fetch_provider(), "webrouter")

    def test_success_returns_title_and_markdown(self):
        client = MagicMock()
        doc = types.SimpleNamespace(title="Example", content="# Example\n\nBody.")
        client.extract.return_value = types.SimpleNamespace(documents=[doc], failures=[])
        result = self._fetch(client)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result, "Title: Example\n\nContent:\n# Example\n\nBody.")
        client.extract.assert_called_once_with(
            "https://example.com/article", format="markdown",
            timeout=web_fetch_module.WEBROUTER_TIMEOUT, data_apis=False,
        )

    def test_empty_content_reports_the_failure(self):
        client = MagicMock()
        failure = types.SimpleNamespace(error="blocked")
        client.extract.return_value = types.SimpleNamespace(documents=[], failures=[failure])
        result = self._fetch(client)
        self.assertEqual(result.status, "error")
        self.assertIn("no content", result.result)
        self.assertIn("blocked", result.result)

    def test_long_failure_message_is_shortened(self):
        client = MagicMock()
        client.extract.side_effect = RuntimeError("x" * 5000)
        result = self._fetch(client)
        self.assertEqual(result.status, "error")
        self.assertLess(len(result.result), 600)

    def test_missing_package_fails_with_install_hint(self):
        client = MagicMock()
        result = self._fetch(client, installed=False)
        self.assertEqual(result.status, "error")
        self.assertIn("pip install webrouter", result.result)
        client.extract.assert_not_called()

    def test_ssrf_guard_still_applies(self):
        client = MagicMock()
        with patch.object(web_fetch_module, "conf", lambda: self._CFG), \
                patch.object(web_fetch_module, "validate_url_safe",
                             side_effect=ValueError("URL resolves to a private address")), \
                _stub_web_router(client):
            result = WebFetch().execute({"url": "http://169.254.169.254/"})
        self.assertEqual(result.status, "error")
        client.extract.assert_not_called()


class TestConsoleWebRouter(unittest.TestCase):
    """The console turns WebRouter on with an empty key, refuses a key, and
    refuses to turn it on without the package."""

    def _save(self, payload, installed=True):
        from channel.web.api.models import ModelsHandler

        with patch("channel.web.api.models.conf", return_value={}), \
                patch.object(web_search_module, "webrouter_installed", return_value=installed), \
                patch.object(ModelsHandler, "_read_file_config", return_value={}), \
                patch.object(ModelsHandler, "_write_file_config") as write:
            out = json.loads(ModelsHandler()._handle_set_search_credential(payload))
        return out, write

    def test_anonymous_save_turns_webrouter_on(self):
        out, write = self._save({"provider": "webrouter", "api_key": "", "anonymous": True})
        self.assertEqual(out["status"], "success")
        self.assertEqual(write.call_args[0][0]["tools"]["web_search"], {"webrouter_enabled": True})

    def test_clear_turns_webrouter_off(self):
        out, write = self._save({"provider": "webrouter", "api_key": ""})
        self.assertEqual(out["status"], "success")
        self.assertEqual(write.call_args[0][0]["tools"]["web_search"], {"webrouter_enabled": False})

    def test_a_key_is_refused(self):
        out, write = self._save({"provider": "webrouter", "api_key": "sk-test", "anonymous": True})
        self.assertEqual(out["status"], "error")
        write.assert_not_called()

    def test_turning_on_without_the_package_is_refused(self):
        out, write = self._save({"provider": "webrouter", "anonymous": True}, installed=False)
        self.assertEqual(out["status"], "error")
        self.assertIn("pip install webrouter", out["message"])
        write.assert_not_called()

    def test_capability_shows_webrouter_as_keyless(self):
        from channel.web.api.models import ModelsHandler

        with patch.object(web_search_module, "webrouter_installed", return_value=True), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            fresh = ModelsHandler._search_capability({})
            on = ModelsHandler._search_capability(_ENABLED)
        fresh_w = {p["id"]: p for p in fresh["providers"]}["webrouter"]
        on_w = {p["id"]: p for p in on["providers"]}["webrouter"]
        self.assertFalse(fresh_w["configured"])
        self.assertTrue(fresh_w["needs_dedicated_key"])
        self.assertTrue(on_w["configured"])
        self.assertTrue(on_w["anonymous"])
        self.assertEqual(on["current_provider"], "webrouter")


if __name__ == "__main__":
    unittest.main()
