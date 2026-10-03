# encoding:utf-8
"""Provider model discovery: GET /models -> editable catalog rows."""

import json

from channel.web.api import models as models_api


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_discover_openai_compatible_models(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        captured.update(url=url, headers=headers, params=params, timeout=timeout)
        return _Response({"data": [{"id": "model-a"}, {"id": "model-b"}, {"id": "model-a"}]})

    monkeypatch.setattr(models_api.requests, "get", fake_get)

    models = models_api._discover_models(
        "openai", api_key="sk-test", api_base="https://api.example.com/v1"
    )

    assert models == ["model-a", "model-b"]
    assert captured["url"] == "https://api.example.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["timeout"] == 10


def test_discover_claude_uses_x_api_key_and_version(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        captured.update(url=url, headers=headers)
        return _Response({"data": [{"id": "claude-sonnet-5"}]})

    monkeypatch.setattr(models_api.requests, "get", fake_get)

    models = models_api._discover_models(
        "claudeAPI", api_key="sk-ant", api_base="https://api.anthropic.com/v1"
    )

    assert models == ["claude-sonnet-5"]
    assert captured["url"] == "https://api.anthropic.com/v1/models"
    assert captured["headers"]["x-api-key"] == "sk-ant"
    assert captured["headers"]["anthropic-version"]


def test_discover_gemini_uses_query_key_and_strips_models_prefix(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        captured.update(url=url, headers=headers, params=params)
        return _Response({"models": [
            {"name": "models/gemini-2.5-pro"},
            {"name": "models/gemini-2.5-flash"},
        ]})

    monkeypatch.setattr(models_api.requests, "get", fake_get)

    models = models_api._discover_models(
        "gemini", api_key="gm-key", api_base="https://generativelanguage.googleapis.com"
    )

    assert models == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models"
    assert captured["params"] == {"key": "gm-key"}


def test_discovery_surfaces_upstream_errors_without_leaking_the_key(monkeypatch):
    monkeypatch.setattr(
        models_api.requests,
        "get",
        lambda *a, **k: _Response({"error": {"message": "bad key sk-secret"}}, status_code=401),
    )

    try:
        models_api._discover_models("openai", api_key="sk-secret", api_base="https://api.example.com/v1")
    except models_api.ModelDiscoveryError as exc:
        assert "401" in str(exc)
        assert "sk-secret" not in str(exc)
    else:
        raise AssertionError("expected ModelDiscoveryError")


def test_handler_uses_saved_key_when_the_ui_sends_a_masked_sentinel(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        models_api,
        "conf",
        lambda: {"open_ai_api_key": "stored-secret", "open_ai_api_base": "https://api.example.com/v1"},
    )
    monkeypatch.setattr(
        models_api,
        "_discover_models",
        lambda provider_id, api_key, api_base: seen.update(
            provider_id=provider_id, api_key=api_key, api_base=api_base
        ) or ["discovered-model"],
    )

    payload = json.loads(models_api.ModelsHandler()._handle_discover_models({
        "provider_id": "openai",
        "api_key": "stor********cret",
    }))

    assert payload["status"] == "success"
    assert payload["models"] == [{"name": "discovered-model", "capabilities": ["text"]}]
    assert seen == {
        "provider_id": "openai",
        "api_key": "stored-secret",
        "api_base": "https://api.example.com/v1",
    }


def test_handler_never_sends_the_saved_key_to_another_base(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        models_api,
        "conf",
        lambda: {"open_ai_api_key": "stored-secret", "open_ai_api_base": "https://api.example.com/v1"},
    )
    monkeypatch.setattr(
        models_api,
        "_discover_models",
        lambda provider_id, api_key, api_base: seen.update(api_key=api_key) or ["m"],
    )

    payload = json.loads(models_api.ModelsHandler()._handle_discover_models({
        "provider_id": "openai",
        "api_key": "stor********cret",
        "api_base": "https://collector.invalid/v1",
    }))

    assert payload["status"] == "error"
    assert seen == {}


def test_discovered_models_get_a_capability_guess():
    guess = models_api._discovered_capabilities
    assert guess("gpt-4o") == ["text"]
    assert guess("text-embedding-3-small") == ["embedding"]
    assert guess("tts-1") == ["tts"]
    assert guess("whisper-1") == ["asr"]
