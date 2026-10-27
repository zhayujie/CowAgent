# encoding:utf-8
"""A non-string web_search config value must not raise out of the tool.

config.json is hand-editable, so `tools.web_search` carrying a JSON boolean or
number is reachable. `_tools_web_search_conf()` guards the *block* type but not
the *value* type, and every call site then does `(value or "").strip()`. The
sites reached before execute()'s try block let the AttributeError leave the tool
entirely instead of turning into a ToolResult.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.web_search import WebSearch
from agent.tools.web_search import web_search as ws

# Only truthy non-strings reach the bug: a falsy value (0, False, "") is already
# absorbed by the `or ""` fallback.
TRUTHY_NON_STRINGS = [True, 1, -1, 3.5, ["local"], {"provider": "local"},
                      (1, 2), b"local"]

_SEARCH_ENV = (
    "DEEPSEEK_API_KEY", "BOCHA_API_KEY", "ZHIPUAI_API_KEY", "QIANFAN_API_KEY", "LINKAI_API_KEY",
    "ANYSEARCH_API_KEY", "SERPLY_API_KEY", "TAVILY_API_KEY", "KEENABLE_API_KEY",
    "SEARXNG_URL",
)


def _conf_web_search(**block):
    """Point config.conf() at a tools.web_search block with the given values."""
    return lambda: {"tools": {"web_search": block}}


class TestWebSearchToleratesNonStringConfig(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {k: "" for k in _SEARCH_ENV})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_a_non_string_api_key_is_read_as_unset(self):
        for bad in TRUTHY_NON_STRINGS:
            with patch.object(ws, "conf", _conf_web_search(tavily_api_key=bad)):
                self.assertEqual(ws._get_api_key("tavily"), "", bad)

    def test_a_non_string_strategy_falls_back_to_auto(self):
        for bad in TRUTHY_NON_STRINGS:
            with patch.object(ws, "conf", _conf_web_search(strategy=bad)):
                self.assertEqual(ws._configured_strategy(), "auto", bad)

    def test_a_non_string_provider_is_read_as_unset(self):
        for bad in TRUTHY_NON_STRINGS:
            with patch.object(ws, "conf", _conf_web_search(provider=bad)):
                self.assertEqual(ws._configured_provider(), "", bad)

    def test_a_non_string_searxng_url_is_read_as_unset(self):
        for bad in TRUTHY_NON_STRINGS:
            with patch.object(ws, "conf", _conf_web_search(searxng_url=bad)):
                self.assertEqual(ws._get_searxng_url(), "", bad)

    def test_execute_returns_a_result_instead_of_raising(self):
        """The pre-try call sites used to let the AttributeError escape."""
        for bad in TRUTHY_NON_STRINGS:
            with patch.object(ws, "conf", _conf_web_search(tavily_api_key=bad)):
                result = WebSearch().execute({"query": "hello"})
            self.assertEqual(result.status, "error", bad)
            self.assertIn("No search provider configured", str(result.result), bad)

    # ---- control: string config still works -----------------------------

    def test_a_string_api_key_is_still_trimmed(self):
        with patch.object(ws, "conf", _conf_web_search(tavily_api_key="  sk-test  ")):
            self.assertEqual(ws._get_api_key("tavily"), "sk-test")

    def test_a_string_strategy_is_still_normalised(self):
        with patch.object(ws, "conf", _conf_web_search(strategy="  FIXED  ")):
            self.assertEqual(ws._configured_strategy(), "fixed")

    def test_an_empty_string_strategy_still_falls_back_to_auto(self):
        with patch.object(ws, "conf", _conf_web_search(strategy="")):
            self.assertEqual(ws._configured_strategy(), "auto")


if __name__ == "__main__":
    unittest.main()
