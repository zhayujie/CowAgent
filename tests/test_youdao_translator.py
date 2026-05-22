# encoding:utf-8
"""
Unit tests for the Youdao translator integration:
  - YoudaoTranslator class behavior (signature, language code mapping,
    request/response handling, error handling).
  - translate.factory.create_translator dispatch and error message.
"""
import os
import sys
import unittest
from hashlib import sha256
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_conf(**values):
    """Build a callable that mimics config.conf() returning the provided dict."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: values.get(key, default))
    return MagicMock(return_value=cfg)


class TestYoudaoTranslatorInit(unittest.TestCase):
    def test_init_success(self):
        with patch(
            "translate.youdao.youdao_translate.conf",
            _mock_conf(
                youdao_translate_app_key="key123",
                youdao_translate_app_secret="secret456",
            ),
        ):
            from translate.youdao.youdao_translate import YoudaoTranslator

            translator = YoudaoTranslator()
            self.assertEqual(translator.app_key, "key123")
            self.assertEqual(translator.app_secret, "secret456")

    def test_init_missing_credentials_raises(self):
        with patch(
            "translate.youdao.youdao_translate.conf",
            _mock_conf(youdao_translate_app_key="", youdao_translate_app_secret=""),
        ):
            from translate.youdao.youdao_translate import YoudaoTranslator

            with self.assertRaises(Exception) as ctx:
                YoudaoTranslator()
            self.assertIn("youdao", str(ctx.exception).lower())


class TestYoudaoTranslatorHelpers(unittest.TestCase):
    def test_truncate_input_short(self):
        from translate.youdao.youdao_translate import YoudaoTranslator

        # length <= 20 -> returned as-is
        self.assertEqual(YoudaoTranslator._truncate_input("hello"), "hello")
        self.assertEqual(YoudaoTranslator._truncate_input("a" * 20), "a" * 20)

    def test_truncate_input_long(self):
        from translate.youdao.youdao_translate import YoudaoTranslator

        # length > 20 -> first 10 + len + last 10
        text = "abcdefghij" + "X" * 5 + "1234567890"  # 25 chars
        result = YoudaoTranslator._truncate_input(text)
        self.assertEqual(result, "abcdefghij" + "25" + "1234567890")

    def test_truncate_input_exactly_21(self):
        from translate.youdao.youdao_translate import YoudaoTranslator

        text = "a" * 21
        result = YoudaoTranslator._truncate_input(text)
        # first 10 'a' + "21" + last 10 'a'
        self.assertEqual(result, "a" * 10 + "21" + "a" * 10)

    def test_convert_lang_known_codes(self):
        from translate.youdao.youdao_translate import YoudaoTranslator

        self.assertEqual(YoudaoTranslator._convert_lang(""), "auto")
        self.assertEqual(YoudaoTranslator._convert_lang("auto"), "auto")
        self.assertEqual(YoudaoTranslator._convert_lang("zh"), "zh-CHS")
        self.assertEqual(YoudaoTranslator._convert_lang("zh-CN"), "zh-CHS")
        self.assertEqual(YoudaoTranslator._convert_lang("zh-TW"), "zh-CHT")

    def test_convert_lang_passthrough(self):
        from translate.youdao.youdao_translate import YoudaoTranslator

        # unknown codes pass through unchanged (Youdao accepts ISO codes for many langs)
        self.assertEqual(YoudaoTranslator._convert_lang("en"), "en")
        self.assertEqual(YoudaoTranslator._convert_lang("ja"), "ja")
        self.assertEqual(YoudaoTranslator._convert_lang("fr"), "fr")

    def test_convert_lang_none(self):
        from translate.youdao.youdao_translate import YoudaoTranslator

        self.assertEqual(YoudaoTranslator._convert_lang(None), "auto")

    def test_build_sign_matches_v3_spec(self):
        with patch(
            "translate.youdao.youdao_translate.conf",
            _mock_conf(
                youdao_translate_app_key="appKey",
                youdao_translate_app_secret="appSecret",
            ),
        ):
            from translate.youdao.youdao_translate import YoudaoTranslator

            translator = YoudaoTranslator()
            query = "hello"
            salt = "saltvalue"
            curtime = "1700000000"
            expected = sha256(
                ("appKey" + "hello" + "saltvalue" + "1700000000" + "appSecret").encode("utf-8")
            ).hexdigest()
            self.assertEqual(translator._build_sign(query, salt, curtime), expected)


class TestYoudaoTranslatorTranslate(unittest.TestCase):
    def _make_translator(self):
        with patch(
            "translate.youdao.youdao_translate.conf",
            _mock_conf(
                youdao_translate_app_key="appKey",
                youdao_translate_app_secret="appSecret",
            ),
        ):
            from translate.youdao.youdao_translate import YoudaoTranslator

            return YoudaoTranslator()

    def test_translate_success(self):
        translator = self._make_translator()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "errorCode": "0",
            "translation": ["你好"],
            "query": "hello",
            "l": "en2zh-CHS",
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "translate.youdao.youdao_translate.requests.post",
            return_value=mock_response,
        ) as mock_post:
            result = translator.translate("hello", from_lang="en", to_lang="zh")

        self.assertEqual(result, "你好")
        mock_post.assert_called_once()
        # Check posted payload contains the right language codes
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["data"]
        self.assertEqual(payload["q"], "hello")
        self.assertEqual(payload["from"], "en")
        self.assertEqual(payload["to"], "zh-CHS")
        self.assertEqual(payload["appKey"], "appKey")
        self.assertEqual(payload["signType"], "v3")
        self.assertIn("salt", payload)
        self.assertIn("sign", payload)
        self.assertIn("curtime", payload)

    def test_translate_multiline_joins_with_newlines(self):
        translator = self._make_translator()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "errorCode": "0",
            "translation": ["line one", "line two"],
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "translate.youdao.youdao_translate.requests.post",
            return_value=mock_response,
        ):
            result = translator.translate("multi\nline")
        self.assertEqual(result, "line one\nline two")

    def test_translate_empty_query_returns_empty(self):
        translator = self._make_translator()
        # Should not even hit the network for an empty query
        with patch("translate.youdao.youdao_translate.requests.post") as mock_post:
            self.assertEqual(translator.translate(""), "")
            mock_post.assert_not_called()

    def test_translate_error_code_raises(self):
        translator = self._make_translator()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "errorCode": "108",
            "msg": "appKey无效",
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "translate.youdao.youdao_translate.requests.post",
            return_value=mock_response,
        ):
            with self.assertRaises(Exception) as ctx:
                translator.translate("hello")
        msg = str(ctx.exception)
        self.assertIn("108", msg)

    def test_translate_empty_translation_raises(self):
        translator = self._make_translator()
        mock_response = MagicMock()
        mock_response.json.return_value = {"errorCode": "0", "translation": []}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "translate.youdao.youdao_translate.requests.post",
            return_value=mock_response,
        ):
            with self.assertRaises(Exception):
                translator.translate("hello")

    def test_translate_default_target_language(self):
        translator = self._make_translator()
        mock_response = MagicMock()
        mock_response.json.return_value = {"errorCode": "0", "translation": ["hello"]}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "translate.youdao.youdao_translate.requests.post",
            return_value=mock_response,
        ) as mock_post:
            translator.translate("你好")  # no from/to provided

        payload = mock_post.call_args.kwargs["data"]
        self.assertEqual(payload["from"], "auto")
        self.assertEqual(payload["to"], "en")


class TestTranslatorFactory(unittest.TestCase):
    def test_factory_creates_youdao(self):
        with patch(
            "translate.youdao.youdao_translate.conf",
            _mock_conf(
                youdao_translate_app_key="k",
                youdao_translate_app_secret="s",
            ),
        ):
            from translate.factory import create_translator
            from translate.youdao.youdao_translate import YoudaoTranslator

            translator = create_translator("youdao")
            self.assertIsInstance(translator, YoudaoTranslator)

    def test_factory_unknown_type_message(self):
        from translate.factory import create_translator

        with self.assertRaises(RuntimeError) as ctx:
            create_translator("nonexistent")
        msg = str(ctx.exception)
        self.assertIn("nonexistent", msg)
        self.assertIn("baidu", msg)
        self.assertIn("youdao", msg)


if __name__ == "__main__":
    unittest.main()
