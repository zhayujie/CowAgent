"""A rejected settings save must not change the running console configuration."""

import copy
import errno
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import web

import config
from channel.web.api.auth import AuthCheckHandler, AuthLoginHandler
from channel.web.api.config import ConfigHandler


@pytest.fixture
def console(tmp_path, monkeypatch):
    original = config.config
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    path = tmp_path / "config.json"
    seed = {
        "model": "gpt-4o-mini",
        "enable_thinking": False,
        "agent_max_steps": 20,
        "web_password": "",
        "subagent": {"enabled": False, "max_concurrent": 7},
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

    def post(updates, cookie=""):
        return app.request(
            "/api/config", method="POST",
            headers={"Content-Type": "application/json", "Cookie": cookie},
            data=json.dumps({"updates": updates}),
        )

    try:
        yield app, post, path, seed
    finally:
        tmp_path.chmod(0o700)
        if path.exists():
            path.chmod(0o600)
        config.config = original


def _require_readonly_permissions(path):
    try:
        with path.open("ab"):
            pass
    except PermissionError:
        return
    pytest.skip("this process can write a read-only file (for example, root)")


def test_readonly_save_keeps_flat_and_borrowed_nested_settings(console):
    _, post, path, _ = console
    previous = copy.deepcopy(dict(config.conf()))
    borrowed = config.conf()["subagent"]
    data = path.read_bytes()
    path.chmod(0o400)
    path.parent.chmod(0o500)
    _require_readonly_permissions(path)
    result = json.loads(post({"enable_thinking": True, "subagent_enabled": True}).data)
    assert result["status"] == "error"
    assert path.read_bytes() == data
    assert dict(config.conf()) == previous
    assert config.conf()["subagent"] is borrowed
    assert borrowed == {"enabled": False, "max_concurrent": 7}


def test_an_external_broken_edit_does_not_change_the_valid_live_config(console):
    _, post, path, _ = console
    previous = copy.deepcopy(dict(config.conf()))
    path.write_text('{ "model": ', encoding="utf-8")
    result = json.loads(post({"enable_thinking": True}).data)
    assert result["status"] == "error"
    assert path.read_text(encoding="utf-8") == '{ "model": '
    assert dict(config.conf()) == previous


def test_replace_failure_keeps_live_settings_and_can_be_retried(console, monkeypatch):
    _, post, path, _ = console
    previous = copy.deepcopy(dict(config.conf()))
    data = path.read_bytes()
    with monkeypatch.context() as failure:
        def fail_replace(*args):
            raise OSError(errno.EIO, "owned storage failure")
        failure.setattr("os.replace", fail_replace)
        result = json.loads(post({"enable_thinking": True, "subagent_enabled": True}).data)
    assert result["status"] == "error"
    assert path.read_bytes() == data
    assert dict(config.conf()) == previous
    result = json.loads(post({"enable_thinking": True, "subagent_enabled": True}).data)
    assert result["status"] == "success"
    assert config.conf()["enable_thinking"] is True
    assert config.conf()["subagent"] == {"enabled": True, "max_concurrent": 7}
    assert json.loads(path.read_text(encoding="utf-8"))["subagent"] == config.conf()["subagent"]


def test_failed_password_clear_keeps_real_get_and_post_authentication(console):
    app, post, path, seed = console
    path.write_text(json.dumps({**seed, "web_password": "owned-test-password"}), encoding="utf-8")
    config.load_config()
    login = app.request("/auth/login", method="POST", headers={"Content-Type": "application/json"},
                        data=json.dumps({"password": "owned-test-password"}))
    assert json.loads(login.data)["status"] == "success"
    cookie = login.headers["Set-Cookie"].split(";", 1)[0]
    data = path.read_bytes()
    path.chmod(0o400)
    path.parent.chmod(0o500)
    _require_readonly_permissions(path)
    assert json.loads(post({"web_password": ""}, cookie).data)["status"] == "error"
    assert path.read_bytes() == data
    assert json.loads(app.request("/auth/check").data) == {
        "status": "success", "auth_required": True, "authenticated": False,
    }
    assert app.request("/api/config").status.startswith("401")
    assert post({"enable_thinking": True}).status.startswith("401")
    authenticated = app.request("/api/config", headers={"Cookie": cookie})
    assert authenticated.status.startswith("200")
    assert json.loads(authenticated.data)["status"] == "success"


def test_a_rejected_value_still_changes_nothing(console):
    _, post, path, _ = console
    previous = copy.deepcopy(dict(config.conf()))
    data = path.read_bytes()
    result = json.loads(post({"enable_thinking": True, "agent_max_steps": ""}).data)
    assert result["status"] == "error"
    assert path.read_bytes() == data
    assert dict(config.conf()) == previous


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_successes_keep_the_committed_and_live_values_in_order(console, monkeypatch, same_key):
    app, post, path, _ = console
    import os
    replace = os.replace
    first_persisted = threading.Event()
    second_started = threading.Event()
    second_done = threading.Event()
    release_first = threading.Event()
    first_thread = None

    def requests_started(handler):
        if threading.current_thread().name != first_thread:
            second_started.set()
        return handler()

    app.add_processor(requests_started)

    def pause_first_replace(source, target):
        replace(source, target)
        if threading.current_thread().name == first_thread:
            first_persisted.set()
            assert release_first.wait(5), "first request was not released"

    monkeypatch.setattr(os, "replace", pause_first_replace)

    def first():
        nonlocal first_thread
        first_thread = threading.current_thread().name
        return post({"enable_thinking": True})

    def second():
        try:
            return post({"enable_thinking": False} if same_key else {"subagent_enabled": True})
        finally:
            second_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        earlier = pool.submit(first)
        try:
            assert first_persisted.wait(5)
            later = pool.submit(second)
            assert second_started.wait(5)
            # Give an un-serialized later save the opportunity to finish. This
            # is a synchronization deadline, not a latency assertion.
            second_done.wait(1)
        finally:
            release_first.set()
        results = [earlier.result(timeout=5), later.result(timeout=5)]
    assert all(json.loads(result.data)["status"] == "success" for result in results)
    saved = json.loads(path.read_text(encoding="utf-8"))
    expected_thinking = not same_key
    assert saved["enable_thinking"] is expected_thinking
    assert config.conf()["enable_thinking"] is expected_thinking
    assert saved["subagent"]["enabled"] is (not same_key)
    assert config.conf()["subagent"] == saved["subagent"]
