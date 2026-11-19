"""Gemini 4 takes its reasoning depth as generationConfig.thinkingConfig.thinkingLevel
and may think for minutes before the first chunk, so it needs a long read timeout."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}


def _call(monkeypatch, model, **kwargs):
    from config import conf
    from models.gemini import google_gemini_bot
    from models.gemini.google_gemini_bot import GoogleGeminiBot

    monkeypatch.setitem(conf(), "gemini_api_key", "test")
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **_):
        captured["payload"] = json
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(google_gemini_bot.requests, "post", fake_post)
    bot = GoogleGeminiBot.__new__(GoogleGeminiBot)
    bot.call_with_tools([{"role": "user", "content": "hi"}], tools=[], stream=False, model=model, **kwargs)
    return captured


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_gemini_4_sends_thinking_level(monkeypatch, effort):
    captured = _call(monkeypatch, "gemini-4-argon", reasoning_effort=effort)

    assert captured["payload"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": effort}
    assert captured["timeout"] == (15, 900)


def test_gemini_4_without_effort_uses_server_default(monkeypatch):
    captured = _call(monkeypatch, "gemini-4-argon")

    assert "generationConfig" not in captured["payload"]


def test_older_gemini_models_are_unchanged(monkeypatch):
    captured = _call(monkeypatch, "gemini-3.8-flash", reasoning_effort="high")

    assert "generationConfig" not in captured["payload"]
    assert captured["timeout"] == 60
