# encoding:utf-8
"""
Unit tests for the web_search tool, focused on the AnySearch, Serply and
Keenable backends.

Covers key resolution (config file + environment fallback), the canonical
provider fallback order, result normalization into the unified output shape,
the AnySearch-specific count clamp (the shared tool schema allows 1-50 while
the API accepts 1-10), HTTP and business-level error mapping, and the
anonymous mode contract (no Authorization header without a key), and the
keyless contract of Keenable (opt-in via ``keenable_anonymous``, mirroring
``anysearch_anonymous``; public endpoint plus the ``X-Keenable-Title`` header
without a key, ``X-API-Key`` with one).

No real network is used: ``requests.post`` / ``requests.get`` are stubbed
throughout.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.web_search import WebSearch
from agent.tools.web_search import web_search as web_search_module


def _fake_response(status_code=200, payload=None):
    """Build a minimal stand-in for a requests Response."""
    resp = MagicMock()
    resp.status_code = status_code
    body = payload if payload is not None else {}
    resp.json = lambda: body
    resp.text = json.dumps(body)
    return resp


def _anysearch_payload(results, total=None, code=0, message="success"):
    """Build an AnySearch /v1/search response body in the documented shape."""
    return {
        "code": code,
        "message": message,
        "request_id": "req-test",
        "data": {
            "results": results,
            "metadata": {"total_results": total if total is not None else len(results)},
        },
    }


class TestAnySearchKeyResolution(unittest.TestCase):
    """The anysearch key lives under tools.web_search, falling back to env."""

    def setUp(self):
        self._prev_env = os.environ.get("ANYSEARCH_API_KEY")
        os.environ.pop("ANYSEARCH_API_KEY", None)

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("ANYSEARCH_API_KEY", None)
        else:
            os.environ["ANYSEARCH_API_KEY"] = self._prev_env

    def test_anysearch_key_from_tools_config(self):
        """tools.web_search.anysearch_api_key is resolved, and wins over env."""
        cfg = {"tools": {"web_search": {"anysearch_api_key": "test-key-123"}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            self.assertEqual(web_search_module._get_api_key("anysearch"), "test-key-123")
            with patch.dict(os.environ, {"ANYSEARCH_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("anysearch"), "test-key-123")

    def test_anysearch_key_env_fallback(self):
        """Without a config value, ANYSEARCH_API_KEY is used; both empty -> ''."""
        with patch.object(web_search_module, "conf", lambda: {}):
            with patch.dict(os.environ, {"ANYSEARCH_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("anysearch"), "env-key-456")
            self.assertEqual(web_search_module._get_api_key("anysearch"), "")


class TestProviderOrder(unittest.TestCase):
    """New providers are appended after the originals, leaving existing routing
    untouched: anysearch, serply, tavily, searxng, then keenable last (its
    keyless tier must come after every provider the user may have paid for)."""

    def test_provider_order_appends_new_providers_last(self):
        self.assertEqual(
            web_search_module.PROVIDER_ORDER,
            ("bocha", "qianfan", "zhipu", "linkai", "anysearch", "serply", "tavily", "searxng", "keenable"),
        )

    def test_web_console_provider_list_stays_in_sync(self):
        """The web console keeps its own copy of the provider order plus the
        set of providers that hold a dedicated key under tools.web_search.
        Both must track the tool module so a new backend shows up in the
        Search panel with the right credential editor."""
        from channel.web.web_channel import ModelsHandler

        self.assertEqual(ModelsHandler._SEARCH_PROVIDERS, web_search_module.PROVIDER_ORDER)
        for pid in web_search_module.PROVIDER_ORDER:
            self.assertIn(pid, ModelsHandler._SEARCH_PROVIDER_LABELS)

        cfg = {"tools": {"web_search": {"serply_api_key": "console-key"}}}
        self.assertEqual(ModelsHandler._search_provider_key("serply", cfg), "console-key")
        with patch.dict(os.environ, {"SERPLY_API_KEY": "env-key"}):
            self.assertEqual(ModelsHandler._search_provider_key("serply", {}), "env-key")
        with patch.dict(os.environ, {"SERPLY_API_KEY": ""}):
            self.assertEqual(ModelsHandler._search_provider_key("serply", {}), "")

        cfg = {"tools": {"web_search": {"keenable_api_key": "console-key"}}}
        self.assertEqual(ModelsHandler._search_provider_key("keenable", cfg), "console-key")
        with patch.dict(os.environ, {"KEENABLE_API_KEY": "env-key"}):
            self.assertEqual(ModelsHandler._search_provider_key("keenable", {}), "env-key")

    def test_web_console_mirrors_keenable_opt_in(self):
        """The Search panel agrees with the tool: keenable is not configured
        on a fresh install, shows as configured and badged anonymous once
        keenable_anonymous is on, and as configured (no badge) with a key."""
        from channel.web.web_channel import ModelsHandler

        with patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            fresh = ModelsHandler._search_capability({})
            anon = ModelsHandler._search_capability(
                {"tools": {"web_search": {"keenable_anonymous": True}}})
            keyed = ModelsHandler._search_capability(
                {"tools": {"web_search": {"keenable_api_key": "sk-test-key"}}})

        fresh_k = {p["id"]: p for p in fresh["providers"]}["keenable"]
        self.assertFalse(fresh_k["configured"])
        self.assertFalse(fresh_k["anonymous"])
        self.assertTrue(fresh_k["needs_dedicated_key"])
        self.assertNotEqual(fresh["current_provider"], "keenable")

        anon_k = {p["id"]: p for p in anon["providers"]}["keenable"]
        self.assertTrue(anon_k["configured"])
        self.assertTrue(anon_k["anonymous"])
        self.assertEqual(anon_k["api_key_masked"], "")
        self.assertEqual(anon["current_provider"], "keenable")

        keyed_k = {p["id"]: p for p in keyed["providers"]}["keenable"]
        self.assertTrue(keyed_k["configured"])
        self.assertFalse(keyed_k["anonymous"])
        self.assertNotEqual(keyed_k["api_key_masked"], "")


_ALL_SEARCH_ENV = (
    "BOCHA_API_KEY", "ZHIPUAI_API_KEY", "QIANFAN_API_KEY", "LINKAI_API_KEY",
    "ANYSEARCH_API_KEY", "SERPLY_API_KEY", "KEENABLE_API_KEY",
)


class TestKeenableOptIn(unittest.TestCase):
    """Keenable's keyless tier is opt-in, mirroring anysearch_anonymous: a
    fresh install configures nothing and the tool is not registered; with
    keenable_anonymous (or a key) keenable is configured. A keyed provider
    still wins because keenable sits last in PROVIDER_ORDER."""

    def test_fresh_install_leaves_keenable_unconfigured(self):
        with patch.object(web_search_module, "conf", lambda: {}), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            self.assertEqual(web_search_module.configured_providers(), [])
            self.assertFalse(web_search_module.WebSearch.is_available())
            self.assertFalse(web_search_module.WebSearch()._resolve_provider(None))

    def test_anysearch_opt_in_does_not_enable_keenable(self):
        cfg = {"tools": {"web_search": {"anysearch_anonymous": True}}}
        with patch.object(web_search_module, "conf", lambda: cfg), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            self.assertEqual(web_search_module.configured_providers(), ["anysearch"])

    def test_anonymous_opt_in_configures_keenable(self):
        cfg = {"tools": {"web_search": {"keenable_anonymous": True}}}
        with patch.object(web_search_module, "conf", lambda: cfg), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            self.assertEqual(web_search_module.configured_providers(), ["keenable"])
            self.assertTrue(web_search_module.WebSearch.is_available())
            self.assertEqual(web_search_module.WebSearch()._resolve_provider(None), "keenable")

    def test_key_configures_keenable_without_opt_in(self):
        cfg = {"tools": {"web_search": {"keenable_api_key": "sk-test"}}}
        with patch.object(web_search_module, "conf", lambda: cfg), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            self.assertEqual(web_search_module.configured_providers(), ["keenable"])
            self.assertTrue(web_search_module.WebSearch.is_available())

    def test_keyed_provider_wins_over_keenable(self):
        cfg = {"tools": {"web_search": {"serply_api_key": "k", "keenable_anonymous": True}}}
        with patch.object(web_search_module, "conf", lambda: cfg), \
                patch.dict(os.environ, {k: "" for k in _ALL_SEARCH_ENV}):
            self.assertEqual(web_search_module.configured_providers(), ["serply", "keenable"])
            self.assertEqual(web_search_module.WebSearch()._resolve_provider(None), "serply")
            self.assertEqual(web_search_module.WebSearch()._resolve_provider("keenable"), "keenable")


class TestConsoleSearchCredential(unittest.TestCase):
    """The console's save path writes keenable_anonymous the same way it does
    anysearch_anonymous: an empty key with anonymous=true turns the tier on,
    a real key turns it off, and clearing the key turns it off again."""

    def _save(self, payload):
        from channel.web.web_channel import ModelsHandler

        with patch("channel.web.web_channel.conf", return_value={}), \
                patch.object(ModelsHandler, "_read_file_config", return_value={}), \
                patch.object(ModelsHandler, "_write_file_config") as write:
            out = json.loads(ModelsHandler()._handle_set_search_credential(payload))
        self.assertEqual(out["status"], "success")
        write.assert_called_once()
        return write.call_args[0][0]["tools"]["web_search"]

    def test_empty_key_with_anonymous_enables_keenable(self):
        ws = self._save({"provider": "keenable", "api_key": "", "anonymous": True})
        self.assertEqual(ws, {"keenable_api_key": "", "keenable_anonymous": True})

    def test_key_disables_anonymous(self):
        ws = self._save({"provider": "keenable", "api_key": "sk-test", "anonymous": True})
        self.assertEqual(ws, {"keenable_api_key": "sk-test", "keenable_anonymous": False})

    def test_clear_disables_anonymous(self):
        ws = self._save({"provider": "keenable", "api_key": ""})
        self.assertEqual(ws, {"keenable_api_key": "", "keenable_anonymous": False})


class TestAnySearchBackend(unittest.TestCase):
    """Behaviour of WebSearch._search_anysearch with a stubbed HTTP layer."""

    def setUp(self):
        self.tool = WebSearch()

    def test_search_anysearch_maps_results(self):
        """Results under data.results map to the unified output shape.

        `total` comes from metadata.total_results; a missing snippet falls
        back to content, truncated to 200 chars. With a key configured, the
        Authorization header is sent.
        """
        long_content = "x" * 300
        payload = _anysearch_payload(
            [
                {"title": "T1", "url": "https://a.example/1", "snippet": "s1", "content": "c1"},
                {"title": "T2", "url": "https://a.example/2", "content": long_content},
            ],
            total=123,
        )
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, payload)) as mock_post:
            result = self.tool._search_anysearch("cowagent", 10)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["backend"], "anysearch")
        self.assertEqual(result.result["total"], 123)
        self.assertEqual(result.result["count"], 2)
        first, second = result.result["results"]
        self.assertEqual(first, {"title": "T1", "url": "https://a.example/1", "snippet": "s1"})
        self.assertEqual(second["snippet"], long_content[:200])
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers.get("Authorization"), "Bearer test-key-123")

    def test_search_anysearch_clamps_count(self):
        """count is clamped into AnySearch's documented 1-10 range.

        A falsy count falls back to the default of 10, matching the
        `count or 10` idiom used by the zhipu/qianfan backends (execute()
        already normalizes out-of-range values to 10 before dispatch).
        """
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            for count, expected in ((50, 10), (0, 10), (None, 10), (10, 10)):
                with self.subTest(count=count):
                    self.tool._search_anysearch("q", count)
                    self.assertEqual(mock_post.call_args[1]["json"]["max_results"], expected)

    def test_search_anysearch_error_status_mapping(self):
        """401/402/429 map to specific messages; other statuses are generic."""
        cases = {
            401: "Invalid AnySearch API key",
            402: "quota exhausted",
            429: "rate limit reached",
            500: "HTTP 500",
        }
        for status_code, fragment in cases.items():
            with self.subTest(status_code=status_code):
                with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                        patch.object(web_search_module.requests, "post",
                                     return_value=_fake_response(status_code)):
                    result = self.tool._search_anysearch("q", 10)
                self.assertEqual(result.status, "error")
                self.assertIn(fragment, result.result)

    def test_search_anysearch_business_error(self):
        """HTTP 200 with a non-zero business code is surfaced as an error."""
        payload = {"code": 40001, "message": "invalid api key", "request_id": "req-test"}
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, payload)):
            result = self.tool._search_anysearch("q", 10)
        self.assertEqual(result.status, "error")
        self.assertIn("code=40001", result.result)
        self.assertIn("invalid api key", result.result)

    def test_search_anysearch_omits_auth_header_without_key(self):
        """Anonymous mode: without a key, no Authorization header is sent."""
        with patch.object(web_search_module, "_get_api_key", return_value=""), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool._search_anysearch("q", 10)
        self.assertEqual(result.status, "success")
        headers = mock_post.call_args[1]["headers"]
        self.assertNotIn("Authorization", headers)

    def test_search_anysearch_ignores_freshness_with_warning(self):
        """freshness='oneWeek' logs a warning and is not sent in the payload."""
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module, "logger") as mock_logger, \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool._search_anysearch("q", 10, freshness="oneWeek")

        self.assertEqual(result.status, "success")
        mock_logger.warning.assert_called_once_with(
            "[WebSearch] anysearch does not support freshness ('oneWeek'); ignoring"
        )
        sent = mock_post.call_args[1]["json"]
        self.assertNotIn("freshness", sent)
        self.assertEqual(sent, {"query": "q", "max_results": 10, "format": "json"})

    def test_search_anysearch_ignores_summary_with_warning(self):
        """summary=True logs a warning; the request payload keeps its plain shape."""
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module, "logger") as mock_logger, \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool._search_anysearch("q", 10, summary=True)

        self.assertEqual(result.status, "success")
        mock_logger.warning.assert_called_once_with(
            "[WebSearch] anysearch does not support summary; ignoring"
        )
        self.assertNotIn("summary", mock_post.call_args[1]["json"])

    def test_search_anysearch_tag_params_passthrough(self):
        """tag and params are passed through to the AnySearch payload."""
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool._search_anysearch("q", 10, tag="finance.quote", search_params={"limit": 5})

        self.assertEqual(result.status, "success")
        sent = mock_post.call_args[1]["json"]
        self.assertEqual(sent["tag"], "finance.quote")
        self.assertEqual(sent["params"], {"limit": 5})

    def test_search_anysearch_config_domain_fallback(self):
        """anysearch_domain config is used when args.tag is absent."""
        cfg = {"tools": {"web_search": {"anysearch_domain": "code.doc", "anysearch_anonymous": True}}}
        with patch.object(web_search_module, "conf", lambda: cfg), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool.execute({"query": "q", "count": 10})

        self.assertEqual(result.status, "success")
        sent = mock_post.call_args[1]["json"]
        self.assertEqual(sent["tag"], "code.doc")

    def test_search_anysearch_zone_language_passthrough(self):
        """zone and language from config are passed to the payload."""
        cfg = {"tools": {"web_search": {"anysearch_zone": "cn", "anysearch_language": "zh-CN", "anysearch_anonymous": True}}}
        with patch.object(web_search_module, "conf", lambda: cfg), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool.execute({"query": "q", "count": 10})

        self.assertEqual(result.status, "success")
        sent = mock_post.call_args[1]["json"]
        self.assertEqual(sent["zone"], "cn")
        self.assertEqual(sent["language"], "zh-CN")

    def test_search_anysearch_ignores_freshness_with_warning(self):
        """freshness='oneWeek' logs a warning and is not sent in the payload."""
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module, "logger") as mock_logger, \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool._search_anysearch("q", 10, freshness="oneWeek")

        self.assertEqual(result.status, "success")
        mock_logger.warning.assert_called_once_with(
            "[WebSearch] anysearch does not support freshness ('oneWeek'); ignoring"
        )
        sent = mock_post.call_args[1]["json"]
        self.assertNotIn("freshness", sent)

    def test_search_anysearch_ignores_summary_with_warning(self):
        """summary=True logs a warning; the request payload keeps its plain shape."""
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module, "logger") as mock_logger, \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _anysearch_payload([]))) as mock_post:
            result = self.tool._search_anysearch("q", 10, summary=True)

        self.assertEqual(result.status, "success")
        mock_logger.warning.assert_called_once_with(
            "[WebSearch] anysearch does not support summary; ignoring"
        )
        self.assertNotIn("summary", mock_post.call_args[1]["json"])

    def test_schema_exposes_vertical_fields_fixed_anysearch(self):
        """fixed=anysearch exposes tag/params in schema."""
        cfg = {"tools": {"web_search": {"strategy": "fixed", "provider": "anysearch", "anysearch_anonymous": True}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            schema = self.tool.get_json_schema()
        props = schema["parameters"]["properties"]
        self.assertIn("tag", props)
        self.assertIn("params", props)

    def test_schema_hides_vertical_fields_auto_multi(self):
        """auto with multiple providers does NOT expose tag/params."""
        cfg = {"tools": {"web_search": {"strategy": "auto", "bocha_api_key": "k1", "anysearch_api_key": "k2"}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            schema = self.tool.get_json_schema()
        props = schema["parameters"]["properties"]
        self.assertNotIn("tag", props)
        self.assertNotIn("params", props)


def _serply_payload(results):
    """Build a Serply /v1/search response body in the documented shape."""
    return {"results": results, "ads": [], "related_questions": []}


class TestSerplyKeyResolution(unittest.TestCase):
    """The serply key lives under tools.web_search, falling back to env."""

    def setUp(self):
        self._prev_env = os.environ.get("SERPLY_API_KEY")
        os.environ.pop("SERPLY_API_KEY", None)

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("SERPLY_API_KEY", None)
        else:
            os.environ["SERPLY_API_KEY"] = self._prev_env

    def test_serply_key_from_tools_config(self):
        """tools.web_search.serply_api_key is resolved, and wins over env."""
        cfg = {"tools": {"web_search": {"serply_api_key": "test-key-123"}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            self.assertEqual(web_search_module._get_api_key("serply"), "test-key-123")
            with patch.dict(os.environ, {"SERPLY_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("serply"), "test-key-123")

    def test_serply_key_env_fallback(self):
        """Without a config value, SERPLY_API_KEY is used; both empty -> ''."""
        with patch.object(web_search_module, "conf", lambda: {}):
            with patch.dict(os.environ, {"SERPLY_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("serply"), "env-key-456")
            self.assertEqual(web_search_module._get_api_key("serply"), "")


class TestSerplyBackend(unittest.TestCase):
    """Behaviour of WebSearch._search_serply with a stubbed HTTP layer."""

    def setUp(self):
        self.tool = web_search_module.WebSearch()

    def test_search_serply_maps_results(self):
        """Serply's title/link/description map to title/url/snippet, and the
        key travels in the X-Api-Key header alongside an explicit User-Agent."""
        payload = _serply_payload([
            {"title": "T1", "link": "https://a.example/1", "description": "s1"},
            {"title": "T2", "link": "https://a.example/2"},
        ])
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "get",
                             return_value=_fake_response(200, payload)) as mock_get:
            result = self.tool._search_serply("cowagent", 10)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["backend"], "serply")
        self.assertEqual(result.result["total"], 2)
        self.assertEqual(result.result["count"], 2)
        first, second = result.result["results"]
        self.assertEqual(first, {"title": "T1", "url": "https://a.example/1", "snippet": "s1"})
        self.assertEqual(second, {"title": "T2", "url": "https://a.example/2", "snippet": ""})
        headers = mock_get.call_args[1]["headers"]
        self.assertEqual(headers.get("X-Api-Key"), "test-key-123")
        self.assertTrue(headers.get("User-Agent"))

    def test_search_serply_clamps_count(self):
        """count is clamped into 1-50 and sent as the `num` query parameter;
        a falsy count falls back to the default of 10."""
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "get",
                             return_value=_fake_response(200, _serply_payload([]))) as mock_get:
            for count, expected in ((50, 50), (99, 50), (0, 10), (None, 10), (10, 10)):
                with self.subTest(count=count):
                    self.tool._search_serply("q", count)
                    url = mock_get.call_args[0][0]
                    self.assertIn(f"num={expected}", url)
                    self.assertIn("q=q", url)

    def test_search_serply_error_status_mapping(self):
        """401/429 map to specific messages; other statuses are generic."""
        cases = {
            401: "Invalid Serply API key",
            429: "rate limit reached",
            500: "HTTP 500",
        }
        for status_code, fragment in cases.items():
            with self.subTest(status_code=status_code):
                with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                        patch.object(web_search_module.requests, "get",
                                     return_value=_fake_response(status_code)):
                    result = self.tool._search_serply("q", 10)
                self.assertEqual(result.status, "error")
                self.assertIn(fragment, result.result)


def _keenable_payload(results):
    """Build a Keenable /v1/search response body in the documented shape."""
    return {"query": "q", "results": results}


class TestKeenableKeyResolution(unittest.TestCase):
    """The keenable key lives under tools.web_search, falling back to env."""

    def setUp(self):
        self._prev_env = os.environ.get("KEENABLE_API_KEY")
        os.environ.pop("KEENABLE_API_KEY", None)

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("KEENABLE_API_KEY", None)
        else:
            os.environ["KEENABLE_API_KEY"] = self._prev_env

    def test_keenable_key_from_tools_config(self):
        """tools.web_search.keenable_api_key is resolved, and wins over env."""
        cfg = {"tools": {"web_search": {"keenable_api_key": "test-key-123"}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            self.assertEqual(web_search_module._get_api_key("keenable"), "test-key-123")
            with patch.dict(os.environ, {"KEENABLE_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("keenable"), "test-key-123")

    def test_keenable_key_env_fallback(self):
        """Without a config value, KEENABLE_API_KEY is used; both empty -> ''."""
        with patch.object(web_search_module, "conf", lambda: {}):
            with patch.dict(os.environ, {"KEENABLE_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("keenable"), "env-key-456")
            self.assertEqual(web_search_module._get_api_key("keenable"), "")


class TestTavilyKeyResolution(unittest.TestCase):
    """The tavily key lives under tools.web_search, falling back to env."""

    def setUp(self):
        self._prev_env = os.environ.get("TAVILY_API_KEY")
        os.environ.pop("TAVILY_API_KEY", None)

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._prev_env

    def test_tavily_key_from_tools_config(self):
        """tools.web_search.tavily_api_key is resolved, and wins over env."""
        cfg = {"tools": {"web_search": {"tavily_api_key": "test-key-123"}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            self.assertEqual(web_search_module._get_api_key("tavily"), "test-key-123")
            with patch.dict(os.environ, {"TAVILY_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("tavily"), "test-key-123")

    def test_tavily_key_env_fallback(self):
        """Without a config value, TAVILY_API_KEY is used; both empty -> ''."""
        with patch.object(web_search_module, "conf", lambda: {}):
            with patch.dict(os.environ, {"TAVILY_API_KEY": "env-key-456"}):
                self.assertEqual(web_search_module._get_api_key("tavily"), "env-key-456")
            self.assertEqual(web_search_module._get_api_key("tavily"), "")


class TestKeenableBackend(unittest.TestCase):
    """Behaviour of WebSearch._search_keenable with a stubbed HTTP layer."""

    def setUp(self):
        self.tool = web_search_module.WebSearch()

    def test_search_keenable_keyless_uses_public_endpoint(self):
        """Without a key the public endpoint is called with the app title
        header and no X-API-Key; `snippet` maps to snippet, falling back to
        `description`, and `published_at` to datePublished."""
        payload = _keenable_payload([
            {"title": "T1", "url": "https://a.example/1", "snippet": "s1", "description": "",
             "published_at": "2026-08-07T09:56:16Z"},
            {"title": "T2", "url": "https://a.example/2", "snippet": "", "description": "d2"},
        ])
        with patch.object(web_search_module, "_get_api_key", return_value=""), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, payload)) as mock_post:
            result = self.tool._search_keenable("cowagent", 10, "noLimit", False)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["backend"], "keenable")
        self.assertEqual(result.result["total"], 2)
        self.assertEqual(result.result["count"], 2)
        first, second = result.result["results"]
        self.assertEqual(first, {"title": "T1", "url": "https://a.example/1", "snippet": "s1",
                                 "datePublished": "2026-08-07T09:56:16Z"})
        self.assertEqual(second["snippet"], "d2")
        self.assertEqual(second["datePublished"], "")

        self.assertEqual(mock_post.call_args[0][0], "https://api.keenable.ai/v1/search/public")
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers.get("X-Keenable-Title"), "cowagent")
        self.assertNotIn("X-API-Key", headers)
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["query"], "cowagent")
        self.assertEqual(body["max_results"], 10)
        self.assertEqual(body["snippet_max_length"], 300)
        self.assertNotIn("published_after", body)

    def test_search_keenable_keyed_uses_authenticated_endpoint(self):
        """With a key the authenticated endpoint is called with X-API-Key; the
        app title header is still sent. summary=True asks for longer snippets."""
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _keenable_payload([]))) as mock_post:
            result = self.tool._search_keenable("q", 10, "noLimit", True)

        self.assertEqual(result.status, "success")
        self.assertEqual(mock_post.call_args[0][0], "https://api.keenable.ai/v1/search")
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers.get("X-API-Key"), "test-key-123")
        self.assertEqual(headers.get("X-Keenable-Title"), "cowagent")
        self.assertEqual(mock_post.call_args[1]["json"]["snippet_max_length"], 1000)

    def test_search_keenable_clamps_count(self):
        """count is clamped into 1-50 and sent as max_results; a falsy count
        falls back to the default of 10."""
        with patch.object(web_search_module, "_get_api_key", return_value=""), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, _keenable_payload([]))) as mock_post:
            for count, expected in ((50, 50), (99, 50), (0, 10), (None, 10), (10, 10)):
                with self.subTest(count=count):
                    self.tool._search_keenable("q", count, "noLimit", False)
                    self.assertEqual(mock_post.call_args[1]["json"]["max_results"], expected)

    def test_search_keenable_freshness_filter(self):
        """Named tokens become published_after; a date range becomes
        published_after + published_before; anything else sends no filter."""
        build = web_search_module.WebSearch._keenable_build_freshness_filter
        self.assertEqual(build("noLimit"), {})
        self.assertEqual(build(""), {})
        self.assertEqual(build("someday"), {})
        self.assertEqual(
            build("2025-01-01..2025-02-01"),
            {"published_after": "2025-01-01", "published_before": "2025-02-01"},
        )
        week = build("oneWeek")
        self.assertEqual(list(week), ["published_after"])
        from datetime import datetime, timedelta
        self.assertEqual(week["published_after"], (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))

    def test_search_keenable_error_status_mapping(self):
        """401/429 map to specific messages; other statuses are generic. A
        keyless 429 points at the optional key, a keyed one does not."""
        cases = {
            401: "Invalid Keenable API key",
            429: "rate limit reached",
            500: "HTTP 500",
        }
        for status_code, fragment in cases.items():
            with self.subTest(status_code=status_code):
                with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                        patch.object(web_search_module.requests, "post",
                                     return_value=_fake_response(status_code)):
                    result = self.tool._search_keenable("q", 10, "noLimit", False)
                self.assertEqual(result.status, "error")
                self.assertIn(fragment, result.result)
                self.assertNotIn("KEENABLE_API_KEY", result.result)

        with patch.object(web_search_module, "_get_api_key", return_value=""), \
                patch.object(web_search_module.requests, "post", return_value=_fake_response(429)):
            result = self.tool._search_keenable("q", 10, "noLimit", False)
        self.assertEqual(result.status, "error")
        self.assertIn("rate limit reached", result.result)
        self.assertIn("KEENABLE_API_KEY", result.result)


class TestTavilyBackend(unittest.TestCase):
    """Behaviour of WebSearch._search_tavily with a stubbed HTTP layer."""

    def setUp(self):
        self.tool = web_search_module.WebSearch()

    def test_search_tavily_maps_results(self):
        """Tavily's content/source/score map to the unified output shape, and
        the query travels in the POST json body alongside the api_key."""
        payload = {
            "results": [
                {"title": "T1", "url": "https://a.example/1", "content": "c1",
                 "source": "a.example", "score": 0.9},
                {"title": "T2", "url": "https://a.example/2"},
            ]
        }
        with patch.object(web_search_module, "_get_api_key", return_value="test-key-123"), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, payload)) as mock_post:
            result = self.tool._search_tavily("cowagent", 10)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["backend"], "tavily")
        self.assertEqual(result.result["total"], 2)
        first, second = result.result["results"]
        self.assertEqual(first["title"], "T1")
        self.assertEqual(first["url"], "https://a.example/1")
        self.assertEqual(first["snippet"], "c1")
        self.assertEqual(first["siteName"], "a.example")
        self.assertEqual(second["snippet"], "")
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["query"], "cowagent")
        self.assertEqual(body["api_key"], "test-key-123")

    def test_search_tavily_clamps_count(self):
        """count is clamped into 1-20 and sent as max_results; falsy -> 10."""
        with patch.object(web_search_module, "_get_api_key", return_value="k"), \
                patch.object(web_search_module.requests, "post",
                             return_value=_fake_response(200, {"results": []})) as mock_post:
            for count, expected in ((20, 20), (99, 20), (0, 10), (None, 10), (5, 5)):
                with self.subTest(count=count):
                    self.tool._search_tavily("q", count)
                    self.assertEqual(mock_post.call_args[1]["json"]["max_results"], expected)

    def test_search_tavily_error_status_mapping(self):
        """401/402/429 map to specific messages; other statuses are generic."""
        cases = {
            401: "Invalid Tavily API key",
            402: "quota exhausted",
            429: "rate limit reached",
            500: "HTTP 500",
        }
        for status_code, fragment in cases.items():
            with self.subTest(status_code=status_code):
                with patch.object(web_search_module, "_get_api_key", return_value="k"), \
                        patch.object(web_search_module.requests, "post",
                                     return_value=_fake_response(status_code)):
                    result = self.tool._search_tavily("q", 10)
                self.assertEqual(result.status, "error")
                self.assertIn(fragment, result.result)


class TestSearxngUrlResolution(unittest.TestCase):
    """SearXNG resolves an instance URL (not an API key) from config or env."""

    def setUp(self):
        self._prev_env = os.environ.get("SEARXNG_URL")
        os.environ.pop("SEARXNG_URL", None)

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("SEARXNG_URL", None)
        else:
            os.environ["SEARXNG_URL"] = self._prev_env

    def test_searxng_url_from_tools_config(self):
        """tools.web_search.searxng_url is resolved, and wins over env."""
        cfg = {"tools": {"web_search": {"searxng_url": "https://searx.example"}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            self.assertEqual(web_search_module._get_searxng_url(), "https://searx.example")
            with patch.dict(os.environ, {"SEARXNG_URL": "https://env.example"}):
                self.assertEqual(web_search_module._get_searxng_url(), "https://searx.example")

    def test_searxng_url_env_fallback(self):
        """Without a config value, SEARXNG_URL is used; both empty -> ''."""
        with patch.object(web_search_module, "conf", lambda: {}):
            with patch.dict(os.environ, {"SEARXNG_URL": "https://env.example"}):
                self.assertEqual(web_search_module._get_searxng_url(), "https://env.example")
            self.assertEqual(web_search_module._get_searxng_url(), "")

    def test_searxng_qualifies_when_url_configured(self):
        """configured_providers() includes searxng once its URL is set."""
        cfg = {"tools": {"web_search": {"searxng_url": "https://searx.example"}}}
        with patch.object(web_search_module, "conf", lambda: cfg):
            self.assertIn("searxng", web_search_module.configured_providers())
        with patch.object(web_search_module, "conf", lambda: {}):
            self.assertNotIn("searxng", web_search_module.configured_providers())


class TestSearxngBackend(unittest.TestCase):
    """Behaviour of WebSearch._search_searxng with a stubbed HTTP layer."""

    def setUp(self):
        self.tool = web_search_module.WebSearch()

    def test_search_searxng_requires_url(self):
        """Without an instance URL, the backend fails fast with guidance."""
        with patch.object(web_search_module, "_get_searxng_url", return_value=""):
            result = self.tool._search_searxng("q", 10)
        self.assertEqual(result.status, "error")
        self.assertIn("SearXNG instance URL not configured", result.result)

    def test_search_searxng_maps_results(self):
        """content/engine map to snippet/siteName; count clamps the list."""
        payload = {
            "results": [
                {"title": "T1", "url": "https://a.example/1", "content": "c1",
                 "engine": "duckduckgo", "score": 1.2},
                {"title": "T2", "url": "https://a.example/2"},
            ]
        }
        with patch.object(web_search_module, "_get_searxng_url", return_value="https://searx.example/"), \
                patch.object(web_search_module.requests, "get",
                             return_value=_fake_response(200, payload)) as mock_get:
            result = self.tool._search_searxng("cowagent", 10)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["backend"], "searxng")
        self.assertEqual(result.result["total"], 2)
        first, second = result.result["results"]
        self.assertEqual(first["snippet"], "c1")
        self.assertEqual(first["siteName"], "duckduckgo")
        self.assertEqual(second["snippet"], "")
        # Trailing slash on the instance URL is normalized; format=json is used.
        url = mock_get.call_args[0][0]
        self.assertIn("https://searx.example/search?", url)
        self.assertIn("format=json", url)

    def test_search_searxng_non_json_response(self):
        """A non-JSON body maps to a clear error message."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(side_effect=ValueError("not json"))
        resp.text = "<html>not json</html>"
        with patch.object(web_search_module, "_get_searxng_url", return_value="https://searx.example"), \
                patch.object(web_search_module.requests, "get", return_value=resp):
            result = self.tool._search_searxng("q", 10)
        self.assertEqual(result.status, "error")
        self.assertIn("non-JSON response", result.result)

    def test_search_searxng_error_status_mapping(self):
        """401/403/429 map to specific messages; other statuses are generic."""
        cases = {
            401: "requires authentication",
            403: "access forbidden",
            429: "rate limit reached",
            500: "HTTP 500",
        }
        for status_code, fragment in cases.items():
            with self.subTest(status_code=status_code):
                with patch.object(web_search_module, "_get_searxng_url", return_value="https://searx.example"), \
                        patch.object(web_search_module.requests, "get",
                                     return_value=_fake_response(status_code)):
                    result = self.tool._search_searxng("q", 10)
                self.assertEqual(result.status, "error")
                self.assertIn(fragment, result.result)

class TestWebSearchDomains(unittest.TestCase):
    """Behaviour of WebSearchDomains with a stubbed HTTP layer."""

    def setUp(self):
        from agent.tools.web_search_domains import WebSearchDomains
        self.tool = WebSearchDomains()

    def test_domains_list_top_level(self):
        """Without domain arg, GET /v1/domains returns top-level list."""
        payload = {"code": 0, "message": "success", "data": {"domains": [{"domain": "finance", "sub_domain_count": 6}]}}
        with patch("agent.tools.web_search_domains.requests.get",
                   return_value=_fake_response(200, payload)) as mock_get:
            result = self.tool.execute({})

        self.assertEqual(result.status, "success")
        mock_get.assert_called_once()
        sent_url = mock_get.call_args[0][0]
        self.assertIn("/v1/domains", sent_url)
        self.assertIn("finance", result.result["domains"])

    def test_domains_sub_domain_lookup(self):
        """With domain arg, GET /v1/sub-domains?domain=finance returns sub-domains."""
        payload = {"code": 0, "message": "success", "data": {"domains": [{"domain": "finance", "sub_domains": [{"sub_domain": "finance.quote"}]}]}}
        with patch("agent.tools.web_search_domains.requests.get",
                   return_value=_fake_response(200, payload)) as mock_get:
            result = self.tool.execute({"domain": "finance"})

        self.assertEqual(result.status, "success")
        sent_url = mock_get.call_args[0][0]
        self.assertIn("/v1/sub-domains", sent_url)
        self.assertIn("domain=finance", sent_url)
        self.assertIn("finance.quote", result.result["domains"])

    def test_domains_401(self):
        """401 returns auth error."""
        with patch("agent.tools.web_search_domains.requests.get",
                   return_value=_fake_response(401, {})):
            result = self.tool.execute({})
        self.assertEqual(result.status, "error")
        self.assertIn("Invalid AnySearch API key", result.result)


class TestWebExtract(unittest.TestCase):
    """Behaviour of WebExtract with a stubbed HTTP layer.

    Error bodies use the official AnySearch error envelope: ``code`` is -1 on
    every failure and the machine-readable reason lives in ``error_code``.
    """

    def setUp(self):
        from agent.tools.web_extract.web_extract import WebExtract
        self.tool = WebExtract()

    # ---- success path (方案 B: same text shape as web_fetch) ----

    def test_extract_success_matches_web_fetch_text_shape(self):
        """Success returns the web_fetch plain-text shape, not a dict."""
        payload = {"code": 0, "message": "success", "data": {
            "url": "https://example.com", "title": "Example", "content": "Hello World"}}
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(200, payload)) as mock_post:
            result = self.tool.execute({"url": "https://example.com"})

        self.assertEqual(result.status, "success")
        self.assertIsInstance(result.result, str)
        self.assertEqual(result.result, "Title: Example\n\nContent:\nHello World")
        self.assertEqual(mock_post.call_args[1]["json"], {"url": "https://example.com"})

    def test_extract_success_appends_truncation_notice(self):
        """Over-limit content is truncated and the notice is appended."""
        long_content = "\n".join(f"line {i}" for i in range(2500))  # over the 2000-line cap
        payload = {"code": 0, "message": "success", "data": {
            "url": "https://example.com", "title": "Example", "content": long_content}}
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(200, payload)):
            result = self.tool.execute({"url": "https://example.com"})

        self.assertEqual(result.status, "success")
        self.assertTrue(result.result.startswith("Title: Example\n\nContent:\nline 0"))
        self.assertIn("[Content truncated: showing 2000 of 2500 lines]", result.result)

    def test_extract_business_error_on_http_200(self):
        """HTTP 200 with code=-1 surfaces the API message."""
        payload = {"code": -1, "error_code": "extract_failed", "message": "upstream exploded"}
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(200, payload)):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("upstream exploded", result.result)

    # ---- Authorization header contract ----

    def test_extract_no_key_omits_authorization_header(self):
        """Anonymous mode: no Authorization header is sent."""
        payload = {"code": 0, "message": "success", "data": {"title": "T", "content": "ok"}}
        with patch("agent.tools.web_extract.web_extract._get_anysearch_api_key", return_value=""):
            with patch("agent.tools.web_extract.web_extract.requests.post",
                       return_value=_fake_response(200, payload)) as mock_post:
                self.tool.execute({"url": "https://example.com"})
        headers = mock_post.call_args[1]["headers"]
        self.assertNotIn("Authorization", headers)

    def test_extract_key_sends_authorization_header(self):
        """With a configured key, Authorization: Bearer <key> is sent."""
        payload = {"code": 0, "message": "success", "data": {"title": "T", "content": "ok"}}
        with patch("agent.tools.web_extract.web_extract._get_anysearch_api_key", return_value="test-key"):
            with patch("agent.tools.web_extract.web_extract.requests.post",
                       return_value=_fake_response(200, payload)) as mock_post:
                self.tool.execute({"url": "https://example.com"})
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer test-key")

    # ---- error_code mapping (official envelope: code=-1 + error_code) ----

    def test_extract_400_invalid_extract_url(self):
        """400 + error_code invalid_extract_url -> canonical message."""
        body = {"code": -1, "error_code": "invalid_extract_url", "message": "url scheme not supported"}
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(400, body)):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.result, "Error: invalid URL for extraction")

    def test_extract_400_unknown_error_code_surfaces_api_message(self):
        """400 with any other error_code falls through and keeps the API detail.

        Regression guard for the dead-code bug: when the `error_code` branch
        misses, the API message must still reach the caller.
        """
        body = {"code": -1, "error_code": "bad_request", "message": "field url is required"}
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(400, body)):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("field url is required", result.result)

    def test_extract_422_extract_failed(self):
        """422 + error_code extract_failed -> canonical message."""
        body = {"code": -1, "error_code": "extract_failed", "message": "page empty"}
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(422, body)):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.result, "Error: extraction failed (page empty or blocked)")

    def test_extract_422_unknown_error_code_surfaces_api_message(self):
        """422 with any other error_code keeps the API detail."""
        body = {"code": -1, "error_code": "unprocessable", "message": "content-type not html"}
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(422, body)):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("content-type not html", result.result)

    def test_extract_401(self):
        """401 returns auth error."""
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(401, {})):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("Invalid AnySearch API key", result.result)

    def test_extract_402_keyed(self):
        """402 with key returns quota exhausted message."""
        with patch("agent.tools.web_extract.web_extract._get_anysearch_api_key", return_value="test-key"):
            with patch("agent.tools.web_extract.web_extract.requests.post",
                       return_value=_fake_response(402, {})):
                result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("quota exhausted", result.result)
        self.assertNotIn("anonymous", result.result)

    def test_extract_402_anonymous(self):
        """402 without key points at configuring an API key."""
        with patch("agent.tools.web_extract.web_extract._get_anysearch_api_key", return_value=""):
            with patch("agent.tools.web_extract.web_extract.requests.post",
                       return_value=_fake_response(402, {})):
                result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("anonymous quota exhausted", result.result)

    def test_extract_429(self):
        """429 returns rate limit message."""
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   return_value=_fake_response(429, {})):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("rate limit", result.result)

    # ---- input validation & network errors ----

    def test_extract_invalid_url(self):
        """Non-HTTP URL is rejected before any request."""
        result = self.tool.execute({"url": "ftp://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("http:// or https://", result.result)

    def test_extract_missing_url(self):
        """Missing url parameter is rejected before any request."""
        result = self.tool.execute({})
        self.assertEqual(result.status, "error")
        self.assertIn("'url' parameter is required", result.result)

    def test_extract_timeout(self):
        """Timeout returns a timed-out error."""
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   side_effect=__import__("requests").Timeout()):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.result)

    def test_extract_connection_error(self):
        """ConnectionError returns a connect failure."""
        with patch("agent.tools.web_extract.web_extract.requests.post",
                   side_effect=__import__("requests").ConnectionError()):
            result = self.tool.execute({"url": "https://example.com"})
        self.assertEqual(result.status, "error")
        self.assertIn("Failed to connect", result.result)

    # ---- availability gate ----

    def test_unavailable_without_key_and_without_anonymous(self):
        """No key and no anonymous opt-in -> tool is not offered."""
        with patch("agent.tools.web_extract.web_extract._get_anysearch_api_key", return_value=""):
            with patch("agent.tools.web_extract.web_extract._anysearch_anonymous_enabled", return_value=False):
                self.assertFalse(self.tool.is_available())

    def test_available_with_key(self):
        """A configured key makes the tool available."""
        with patch("agent.tools.web_extract.web_extract._get_anysearch_api_key", return_value="test-key"):
            with patch("agent.tools.web_extract.web_extract._anysearch_anonymous_enabled", return_value=False):
                self.assertTrue(self.tool.is_available())

    def test_available_with_anonymous_opt_in(self):
        """anysearch_anonymous opt-in makes the tool available without a key."""
        with patch("agent.tools.web_extract.web_extract._get_anysearch_api_key", return_value=""):
            with patch("agent.tools.web_extract.web_extract._anysearch_anonymous_enabled", return_value=True):
                self.assertTrue(self.tool.is_available())

if __name__ == "__main__":
    unittest.main()
