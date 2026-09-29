# encoding:utf-8
"""
Unit tests for the Baidu translator's request handling.

Covers the retry logic (when every attempt hits the transient error codes
52001/52002, translate() must report the API error instead of a bare KeyError
on the missing trans_result field) plus the request itself: every attempt is
bounded, and an HTTP-level failure with a non-JSON body is reported with its
status rather than as a decode error.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_conf(**values):
    """Build a callable that mimics config.conf() returning the provided dict."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: values.get(key, default))
    return MagicMock(return_value=cfg)


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def _make_translator():
    with patch(
        "translate.baidu.baidu_translate.conf",
        _mock_conf(baidu_translate_app_id="appid123", baidu_translate_app_key="appkey456"),
    ):
        from translate.baidu.baidu_translate import BaiduTranslator

        return BaiduTranslator()


class TestBaiduTranslatorTranslate(unittest.TestCase):
    def _post_returning(self, **kwargs):
        return patch("translate.baidu.baidu_translate.requests.post", **kwargs)

    def test_translate_success(self):
        translator = _make_translator()
        payload = {"trans_result": [{"src": "hello", "dst": "你好"}]}

        with self._post_returning(return_value=_response(payload)) as mock_post:
            result = translator.translate("hello", from_lang="en", to_lang="zh")

        self.assertEqual(result, "你好")
        mock_post.assert_called_once()
        sent = mock_post.call_args.kwargs["params"]
        self.assertEqual(sent["q"], "hello")
        self.assertEqual(sent["from"], "en")
        self.assertEqual(sent["to"], "zh")

    def test_translate_retries_transient_error_then_succeeds(self):
        translator = _make_translator()
        responses = [
            _response({"error_code": "52002", "error_msg": "系统错误"}),
            _response({"trans_result": [{"dst": "你好"}]}),
        ]

        with self._post_returning(side_effect=responses) as mock_post:
            result = translator.translate("hello")

        self.assertEqual(result, "你好")
        self.assertEqual(mock_post.call_count, 2)

    def test_translate_non_retryable_error_raises_immediately(self):
        translator = _make_translator()

        with self._post_returning(
            return_value=_response({"error_code": "54001", "error_msg": "Invalid Sign"})
        ) as mock_post:
            with self.assertRaises(Exception) as ctx:
                translator.translate("hello")

        self.assertIn("Invalid Sign", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 1)

    def test_translate_retries_exhausted_raises_api_error(self):
        """Every attempt hits a transient error: report it instead of a KeyError."""
        translator = _make_translator()

        with self._post_returning(
            return_value=_response({"error_code": "52001", "error_msg": "请求超时"})
        ) as mock_post:
            with self.assertRaises(Exception) as ctx:
                translator.translate("hello")

        # 3 attempts, then a readable error rather than KeyError: 'trans_result'
        self.assertEqual(mock_post.call_count, 3)
        self.assertNotIsInstance(ctx.exception, KeyError)
        self.assertIn("请求超时", str(ctx.exception))

    def test_every_attempt_is_bounded(self):
        """requests waits forever by default; three attempts would triple that."""
        translator = _make_translator()

        with self._post_returning(
            return_value=_response({"error_code": "52001", "error_msg": "请求超时"})
        ) as mock_post:
            with self.assertRaises(Exception):
                translator.translate("hello")

        self.assertEqual(mock_post.call_count, 3)
        for attempt in mock_post.call_args_list:
            timeout = attempt.kwargs.get("timeout")
            self.assertIsInstance(timeout, (int, float))
            self.assertGreater(timeout, 0)

    def test_non_json_error_body_is_reported_with_its_status(self):
        """A gateway HTML page must not surface as a bare JSONDecodeError."""
        translator = _make_translator()
        response = MagicMock()
        response.status_code = 502
        response.text = "<html>Bad Gateway</html>"
        response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

        with self._post_returning(return_value=response):
            with self.assertRaises(Exception) as ctx:
                translator.translate("hello")

        self.assertNotIsInstance(ctx.exception, ValueError)
        self.assertIn("502", str(ctx.exception))
        self.assertIn("Bad Gateway", str(ctx.exception))
