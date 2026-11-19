"""A models-tab save and any other console save must not overwrite each other.

Every console handler rewrites the whole of config.json: it reads the file,
changes a few keys and writes the dict back. ``ConfigHandler.POST`` and
``integrations.save_config_values`` hold ``_settings_save_lock`` across that
read-modify-write, and #3893 gave the channel handlers the same guard. The
models tab -- the largest handler in the console, with a dozen write actions --
still had none, so a model/credential edit overlapping a settings or channel
save wrote back the copy it read before that save landed and silently dropped
its keys. The file stays valid, so nothing reports an error.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import web

import config
from channel.web.api import models as models_api
from channel.web.api.auth import AuthCheckHandler, AuthLoginHandler
from channel.web.api.config import ConfigHandler
from channel.web.api.models import ModelsHandler


SEED = {
    "model": "gpt-4o-mini",
    "enable_thinking": False,
    "web_password": "",
    "deepseek_api_key": "",
    "channel_type": "dingtalk",
}

# Each of these actions reaches _write_config_file_for_write on master.
WRITE_ACTIONS = [
    pytest.param(
        {"action": "set_provider", "provider_id": "deepseek", "api_key": "sk-lock"},
        id="set_provider",
    ),
    pytest.param(
        {"action": "delete_provider", "provider_id": "deepseek"},
        id="delete_provider",
    ),
    pytest.param(
        {"action": "set_voice_reply_mode", "mode": "always"},
        id="set_voice_reply_mode",
    ),
    pytest.param(
        {"action": "set_search_provider_enabled", "provider": "tavily", "enabled": False},
        id="set_search_provider_enabled",
    ),
    pytest.param(
        {"action": "set_search_credential", "provider": "tavily", "api_key": "tv-key"},
        id="set_search_credential",
    ),
    pytest.param(
        {"action": "set_capability", "capability": "image",
         "provider_id": "gemini", "model": "gemini-3-pro-image-preview"},
        id="set_capability_image",
    ),
]


@pytest.fixture
def console(tmp_path, monkeypatch):
    original = config.config
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(SEED), encoding="utf-8")
    config.load_config()
    app = web.application(
        ("/api/config", "ConfigHandler",
         "/api/models", "ModelsHandler",
         "/auth/login", "AuthLoginHandler",
         "/auth/check", "AuthCheckHandler"),
        {"ConfigHandler": ConfigHandler, "ModelsHandler": ModelsHandler,
         "AuthLoginHandler": AuthLoginHandler, "AuthCheckHandler": AuthCheckHandler},
        autoreload=False,
    )
    # Rebuilding Bridge is unrelated to the file write and needs a live bot.
    monkeypatch.setattr(ModelsHandler, "_reset_bridge", staticmethod(lambda: None))

    def post_models(payload):
        return app.request(
            "/api/models", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
        )

    def save_settings(updates):
        return app.request(
            "/api/config", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"updates": updates}),
        )

    try:
        yield post_models, save_settings, path
    finally:
        config.config = original


def _record_lock_on_write(monkeypatch):
    observed = []
    real = models_api._write_config_file_for_write

    def record(config_path, data):
        from channel.web.api.config import _settings_save_lock
        observed.append(_settings_save_lock.locked())
        return real(config_path, data)

    monkeypatch.setattr(models_api, "_write_config_file_for_write", record)
    return observed


@pytest.mark.parametrize("payload", WRITE_ACTIONS)
def test_every_models_config_write_holds_the_settings_lock(console, monkeypatch, payload):
    post_models, _, _ = console
    observed = _record_lock_on_write(monkeypatch)

    resp = post_models(payload)

    assert json.loads(resp.data)["status"] == "success"
    assert observed, "the models action did not write config.json"
    assert all(observed), "a models config write ran without the settings save lock"


def test_a_concurrent_settings_save_keeps_the_models_change(console, monkeypatch):
    """A settings save landing inside the models read/write window survives."""
    post_models, save_settings, path = console
    real_read = models_api._read_config_file_for_write
    models_read = threading.Event()
    release_models = threading.Event()
    settings_done = threading.Event()

    def pause_models_read():
        # Read first, then hold the stale copy while the settings save runs.
        stale = real_read()
        models_read.set()
        assert release_models.wait(5), "the models write was never released"
        return stale

    monkeypatch.setattr(models_api, "_read_config_file_for_write", pause_models_read)

    def settings():
        try:
            return save_settings({"enable_thinking": True})
        finally:
            settings_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        models = pool.submit(post_models, {
            "action": "set_provider", "provider_id": "deepseek", "api_key": "sk-lock"})
        try:
            assert models_read.wait(5)
            other = pool.submit(settings)
            # Give an un-serialized save the chance to finish inside the window
            # the models write holds. A synchronization deadline, not a
            # latency assertion.
            settings_done.wait(1)
        finally:
            release_models.set()
        models.result(timeout=5)
        saved = json.loads(other.result(timeout=5).data)

    assert saved["status"] == "success"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    # Both writes happened; neither may be lost.
    assert on_disk["deepseek_api_key"] == "sk-lock"
    assert on_disk["enable_thinking"] is True
    assert config.conf()["enable_thinking"] is True


def test_a_plain_models_save_still_succeeds(console):
    """Control: serializing the writes must not change a single save's result."""
    post_models, _, path = console

    resp = post_models({
        "action": "set_provider", "provider_id": "deepseek", "api_key": "sk-lock"})

    assert json.loads(resp.data)["status"] == "success"
    assert json.loads(path.read_text(encoding="utf-8"))["deepseek_api_key"] == "sk-lock"
    assert config.conf()["deepseek_api_key"] == "sk-lock"


def test_model_discovery_does_not_hold_the_save_lock(console, monkeypatch):
    """Discovery calls a provider's /models endpoint (up to 10s): no lock held."""
    post_models, _, _ = console
    seen = []

    def fake_discover(self, data):
        from channel.web.api.config import _settings_save_lock
        seen.append(_settings_save_lock.locked())
        return json.dumps({"status": "success", "provider_id": data.get("provider_id"),
                           "models": [], "count": 0})

    monkeypatch.setattr(ModelsHandler, "_handle_discover_models", fake_discover)

    resp = post_models({"action": "discover_models", "provider_id": "deepseek"})

    assert json.loads(resp.data)["status"] == "success"
    assert seen == [False], "a read-only network probe held the config save lock"
