"""bocha responses with a null webPages block must parse to zero results.

The bocha API answers no-result queries with "webPages": null. A
`.get("webPages", {})` default only covers a *missing* key, so the null
form fell straight into `.get("value")` on None and the whole search came
back as "Error: Search failed - 'NoneType' object has no attribute 'get'"
instead of an empty result list.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "tests")

from agent.tools.web_search import web_search as web_search_module
from agent.tools.web_search.web_search import WebSearch


def _resp(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


class TestBochaNullWebPages(unittest.TestCase):

    def setUp(self):
        self.tool = WebSearch({})
        self.patchers = [
            patch.object(web_search_module, "_get_api_key", lambda name: "k"),
            patch.object(web_search_module.requests, "post"),
        ]
        self.post = self.patchers[1].start()
        self.patchers[0].start()
        self.addCleanup(lambda: [p.stop() for p in self.patchers])

    def test_null_web_pages_returns_zero_results(self):
        self.post.return_value = _resp({"code": 200, "data": {"webPages": None}})
        result = self.tool._search_bocha("qq", 5, "no-limit", False)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["results"], [])
        self.assertEqual(result.result["total"], 0)

    def test_missing_web_pages_block_still_returns_zero_results(self):
        self.post.return_value = _resp({"code": 200, "data": {}})
        result = self.tool._search_bocha("qq", 5, "no-limit", False)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["results"], [])

    def test_a_populated_block_still_parses(self):
        self.post.return_value = _resp({
            "code": 200,
            "data": {"webPages": {"totalEstimatedMatches": 1, "value": [
                {"name": "t", "url": "https://x", "snippet": "s"}
            ]}},
        })
        result = self.tool._search_bocha("qq", 5, "no-limit", False)
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.result["results"]), 1)
        self.assertEqual(result.result["total"], 1)


if __name__ == "__main__":
    unittest.main()
