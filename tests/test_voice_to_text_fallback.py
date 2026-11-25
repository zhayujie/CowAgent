# encoding:utf-8
"""Bridge.fetch_voice_to_text in auto mode.

An unset voice_to_text means "follow the main model": the main model's vendor
is tried first, then every other vendor that has an api key, so one failing
vendor does not cost the user their voice message. A provider the user picked
explicitly is used alone.
"""
import unittest
from unittest.mock import MagicMock, patch

from bridge.reply import Reply, ReplyType


def _conf(**values):
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: values.get(key, default))
    return MagicMock(return_value=cfg)


class _Voice:
    def __init__(self, name, calls, outcome):
        self.name, self.calls, self.outcome = name, calls, outcome

    def voiceToText(self, path):
        self.calls.append(self.name)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _bridge(chat, outcomes, **config):
    """A Bridge routed to ``chat`` whose voice vendors answer ``outcomes``."""
    from bridge.bridge import Bridge

    calls = []
    bridge = Bridge.__wrapped__.__new__(Bridge.__wrapped__)
    bridge.btype = {"chat": chat, "voice_to_text": "openai"}
    bridge.asr_bots = {}
    factory = patch(
        "bridge.bridge.create_voice",
        side_effect=lambda name: _Voice(name, calls, outcomes.get(name, Reply(ReplyType.TEXT, name))),
    )
    return bridge, calls, factory, patch("bridge.bridge.conf", _conf(**config))


KEYS = dict(deepseek_api_key="d", linkai_api_key="l", dashscope_api_key="q")


class TestVoiceToTextFallback(unittest.TestCase):
    def test_main_model_vendor_goes_first(self):
        bridge, calls, factory, conf = _bridge("linkai", {}, use_linkai=True, **KEYS)
        with factory, conf:
            reply = bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(calls, ["linkai"])
        self.assertEqual(reply.content, "linkai")

    def test_failed_vendor_falls_through_to_the_next_configured_one(self):
        outcomes = {"linkai": Reply(ReplyType.ERROR, "quota"), "deepseek": RuntimeError("down")}
        bridge, calls, factory, conf = _bridge("linkai", outcomes, **KEYS)
        with factory, conf:
            reply = bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(calls, ["linkai", "deepseek", "dashscope"])
        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(reply.content, "dashscope")

    def test_last_failure_is_returned_when_every_vendor_fails(self):
        outcomes = {name: Reply(ReplyType.ERROR, name) for name in ("linkai", "deepseek", "dashscope")}
        bridge, calls, factory, conf = _bridge("linkai", outcomes, **KEYS)
        with factory, conf:
            reply = bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertEqual(reply.content, "dashscope")

    def test_main_vendor_without_asr_uses_the_configured_ones(self):
        bridge, calls, factory, conf = _bridge("claudeAPI", {}, claude_api_key="c", mimo_api_key="m")
        with factory, conf:
            bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(calls, ["mimo"])

    def test_main_vendor_without_a_key_is_skipped(self):
        bridge, calls, factory, conf = _bridge("deepseek", {}, linkai_api_key="l")
        with factory, conf:
            bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(calls, ["linkai"])

    def test_explicit_provider_is_used_alone(self):
        outcomes = {"zhipu": Reply(ReplyType.ERROR, "bad key")}
        bridge, calls, factory, conf = _bridge("linkai", outcomes, voice_to_text="zhipu", **KEYS)
        with factory, conf:
            reply = bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(calls, ["zhipu"])
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_legacy_openai_setting_still_routes_to_linkai(self):
        bridge, calls, factory, conf = _bridge(
            "linkai", {}, voice_to_text="openai", use_linkai=True, **KEYS)
        with factory, conf:
            bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(calls, ["linkai"])

    def test_nothing_configured_keeps_the_missing_key_error_path(self):
        bridge, calls, factory, conf = _bridge("claudeAPI", {})
        with factory, conf:
            bridge.fetch_voice_to_text("/tmp/a.ogg")
        self.assertEqual(calls, ["openai"])


if __name__ == "__main__":
    unittest.main()
