# encoding:utf-8
"""
Unit tests for the LiteLLM provider (models/litellm/litellm_bot.py).

`litellm` is lazy-imported inside the bot, so these tests stub it in
``sys.modules`` before it is used. No network access.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module
from config import Config


def set_conf(d):
    config_module.config = Config(d)


def install_litellm_stub(content="hello", raise_exc=None):
    """Install a fake litellm module; return its completion spy (with .calls)."""
    fake = types.ModuleType("litellm")

    def completion(**kwargs):
        completion.calls.append(kwargs)
        if raise_exc is not None:
            raise raise_exc
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        usage = types.SimpleNamespace(total_tokens=42, completion_tokens=10, prompt_tokens=32)
        return types.SimpleNamespace(choices=[choice], usage=usage)

    completion.calls = []
    fake.completion = completion
    sys.modules["litellm"] = fake
    return completion


BASE_CONF = {
    "bot_type": "litellm",
    "model": "anthropic/claude-3-5-sonnet",
    "litellm_api_key": "sk-test",
    "litellm_base_url": "http://localhost:4000",
    "temperature": 0.5,
    "top_p": 0.9,
}


class TestFactory(unittest.TestCase):
    def test_factory_returns_litellm_bot(self):
        set_conf(dict(BASE_CONF))
        install_litellm_stub()
        import common.const as const
        from models.bot_factory import create_bot
        from models.litellm.litellm_bot import LiteLLMBot
        bot = create_bot(const.LITELLM)
        self.assertIsInstance(bot, LiteLLMBot)


class TestReplyText(unittest.TestCase):
    def _bot(self, conf):
        set_conf(conf)
        from models.litellm.litellm_bot import LiteLLMBot
        return LiteLLMBot()

    def test_dispatch_forwards_model_creds_and_drop_params(self):
        spy = install_litellm_stub(content="4")
        bot = self._bot(dict(BASE_CONF))
        from models.litellm.litellm_session import LiteLLMSession
        session = LiteLLMSession("s1", model="anthropic/claude-3-5-sonnet")
        session.messages = [{"role": "user", "content": "2+2?"}]
        out = bot.reply_text(session)
        self.assertEqual(out["content"], "4")
        self.assertEqual(out["total_tokens"], 42)
        call = spy.calls[0]
        self.assertEqual(call["model"], "anthropic/claude-3-5-sonnet")
        self.assertTrue(call["drop_params"])
        self.assertEqual(call["api_key"], "sk-test")
        self.assertEqual(call["api_base"], "http://localhost:4000")

    def test_credentials_omitted_when_blank(self):
        spy = install_litellm_stub()
        conf = dict(BASE_CONF)
        conf["litellm_api_key"] = ""
        conf["litellm_base_url"] = ""
        bot = self._bot(conf)
        from models.litellm.litellm_session import LiteLLMSession
        session = LiteLLMSession("s2", model=conf["model"])
        session.messages = [{"role": "user", "content": "hi"}]
        bot.reply_text(session)
        call = spy.calls[0]
        self.assertNotIn("api_key", call)
        self.assertNotIn("api_base", call)
        self.assertTrue(call["drop_params"])

    def test_transient_error_returns_error_content(self):
        err = type("RateLimitError", (Exception,), {})("429")
        install_litellm_stub(raise_exc=err)
        bot = self._bot(dict(BASE_CONF))
        from models.litellm.litellm_session import LiteLLMSession
        session = LiteLLMSession("s3", model=BASE_CONF["model"])
        session.messages = [{"role": "user", "content": "hi"}]
        out = bot.reply_text(session)
        self.assertEqual(out["completion_tokens"], 0)
        self.assertIn("LiteLLM error", out["content"])


if __name__ == "__main__":
    unittest.main()
