# encoding: utf-8
"""Smoke tests for Qiniu MaaS provider registration."""

import unittest

from common import const
from models.bot_factory import create_bot


class TestQiniuProvider(unittest.TestCase):
    def test_qiniu_constant_and_default_model(self):
        self.assertEqual(const.QINIU, "qiniu")
        self.assertEqual(const.QINIU_DEFAULT_MODEL, "deepseek-v3")
        self.assertIn(const.QINIU_DEFAULT_MODEL, const.MODEL_LIST)

    def test_create_bot_qiniu(self):
        bot = create_bot(const.QINIU)
        self.assertEqual(type(bot).__name__, "QiniuBot")


if __name__ == "__main__":
    unittest.main()
