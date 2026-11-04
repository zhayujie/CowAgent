"""A channel config write and a settings save must not overwrite each other.

Every console handler rewrites the whole of config.json: read the file, change
a few keys, write the dict back. Two of those running at the same time each
write back the copy they read, so the one that finishes last drops everything
the other changed. The settings handler already serializes this with its
``_settings_save_lock`` (see tests/test_web_config_save_transaction.py); these
tests pin the same guarantee for the channel handlers.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import web

import config
from channel.web.api import channels as channels_api
from channel.web.api.auth import AuthCheckHandler, AuthLoginHandler
from channel.web.api.channels import ChannelsHandler
from channel.web.api.config import ConfigHandler


@pytest.fixture
def console(tmp_path, monkeypatch):
    original = config.config
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    path = tmp_path / "config.json"
    seed = {
        "model": "gpt-4o-mini",
        "enable_thinking": False,
        "web_password": "",
        "channel_type": "dingtalk",
        "dingtalk_client_id": "",
        "dingtalk_client_secret": "",
    }
    path.write_text(json.dumps(seed), encoding="utf-8")
    config.load_config()
    app = web.application(
        ("/api/config", "ConfigHandler", "/auth/login", "AuthLoginHandler",
         "/auth/check", "AuthCheckHandler"),
        {"ConfigHandler": ConfigHandler, "AuthLoginHandler": AuthLoginHandler,
         "AuthCheckHandler": AuthCheckHandler},
        autoreload=False,
    )

    def save_settings(updates):
        return app.request(
            "/api/config", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"updates": updates}),
        )

    # Neither the connect nor the disconnect path may reach a real manager here.
    monkeypatch.setattr(channels_api, "_live_channel_manager", lambda: None)
    try:
        yield save_settings, path, seed
    finally:
        config.config = original


def _write_under_lock(monkeypatch):
    """Record, per write, whether the console save lock was held at the time."""
    observed = []
    real = channels_api._write_config_file_for_write

    def record(config_path, data):
        from channel.web.api.config import _settings_save_lock
        observed.append(_settings_save_lock.locked())
        real(config_path, data)

    monkeypatch.setattr(channels_api, "_write_config_file_for_write", record)
    return observed


@pytest.mark.parametrize("entry_point", ["save", "connect", "disconnect", "prune"])
def test_every_channel_config_write_holds_the_settings_lock(
    console, monkeypatch, entry_point
):
    _, _, _ = console
    handler = ChannelsHandler()
    observed = _write_under_lock(monkeypatch)

    if entry_point == "save":
        handler._handle_save("dingtalk", {"dingtalk_client_id": "abc"})
    elif entry_point == "connect":
        handler._handle_connect("dingtalk", {"dingtalk_client_id": "abc"})
    elif entry_point == "disconnect":
        handler._handle_disconnect("dingtalk")
    else:
        handler._prune_legacy_channel_type("dingtalk", [])

    assert observed, "the handler did not write config.json"
    assert all(observed), "a channel config write ran without the settings save lock"


def test_a_concurrent_settings_save_keeps_the_channel_change(console, monkeypatch):
    save_settings, path, _ = console
    handler = ChannelsHandler()
    real_read = channels_api._read_config_file_for_write
    channel_read = threading.Event()
    release_channel = threading.Event()
    settings_done = threading.Event()
    channel_thread = None

    def pause_channel_read():
        # Read first, then hold the stale copy while the settings save runs.
        stale = real_read()
        channel_read.set()
        assert release_channel.wait(5), "the channel write was never released"
        return stale

    monkeypatch.setattr(channels_api, "_read_config_file_for_write", pause_channel_read)

    def disconnect():
        nonlocal channel_thread
        channel_thread = threading.current_thread().name
        return handler._handle_disconnect("dingtalk")

    def settings():
        try:
            return save_settings({"enable_thinking": True})
        finally:
            settings_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        channel = pool.submit(disconnect)
        try:
            assert channel_read.wait(5)
            other = pool.submit(settings)
            # Give an un-serialized save the chance to finish inside the window
            # the channel write holds. A synchronization deadline, not a
            # latency assertion.
            settings_done.wait(1)
        finally:
            release_channel.set()
        channel.result(timeout=5)
        saved = json.loads(other.result(timeout=5).data)

    assert saved["status"] == "success"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    # Both writes happened; neither may be lost.
    assert on_disk["channel_type"] == ""
    assert on_disk["enable_thinking"] is True
    assert config.conf()["enable_thinking"] is True
