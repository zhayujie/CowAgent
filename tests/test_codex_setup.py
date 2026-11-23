"""Regression tests for managed Codex installation and web authorization."""

import hashlib
import io
from pathlib import Path
import tarfile
from threading import Event
import time
from types import SimpleNamespace

import pytest

from models.codex import install, web_login


def _wait_for(setup, phase):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = setup.dispatch("status")
        if state["phase"] == phase:
            return state
        time.sleep(0.01)
    pytest.fail(f"Codex did not reach {phase}: {setup.dispatch('status')}")


def test_install_verifies_archive_before_publishing(monkeypatch, tmp_path):
    payload = b"test executable"
    archive = io.BytesIO()
    target = "x86_64-unknown-linux-musl"
    with tarfile.open(fileobj=archive, mode="w:gz") as package:
        member = tarfile.TarInfo("codex-" + target)
        member.size = len(payload)
        package.addfile(member, io.BytesIO(payload))

    monkeypatch.setattr(install.platform, "system", lambda: "Linux")
    monkeypatch.setattr(install.platform, "machine", lambda: "x86_64")
    # A codex on PATH is never used in place of the pinned build.
    monkeypatch.setattr(install.shutil, "which", lambda _name: "/usr/bin/codex")
    assert install.find_codex(tmp_path) is None
    monkeypatch.setattr(install, "urlopen", lambda *args, **kwargs: io.BytesIO(archive.getvalue()))
    monkeypatch.setattr(install.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout=f"codex-cli {install.VERSION}\n".encode(), returncode=0,
    ))

    monkeypatch.setitem(install._ASSETS, target, "0" * 64)
    with pytest.raises(install.InstallError, match="SHA-256"):
        install.install_codex(tmp_path)
    assert install.find_codex(tmp_path) is None

    monkeypatch.setitem(install._ASSETS, target, hashlib.sha256(archive.getvalue()).hexdigest())
    binary = Path(install.install_codex(tmp_path))
    assert binary.parent == tmp_path / "bin"
    assert binary.read_bytes() == payload
    assert install.install_codex(tmp_path) == str(binary)
    assert list(binary.parent.iterdir()) == [binary]


@pytest.mark.parametrize("cancel", [False, True])
def test_web_setup_installs_signs_in_and_syncs(monkeypatch, tmp_path, cancel):
    authorize = Event()
    calls = []
    installed = False

    def install_cli(home, progress=None):
        nonlocal installed
        assert home == tmp_path
        calls.append("install")
        progress(1024, 2048)
        installed = True

    class Server:
        def __init__(self, timeout):
            assert timeout > 120

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            calls.append("close")

        def request(self, method, params, **kwargs):
            calls.append(method)
            if method == "account/login/start":
                assert params["type"] == "chatgptDeviceCode" and kwargs["preserve_events"]
                return {
                    "loginId": "session-id", "verificationUrl": "https://auth.openai.com/codex/device",
                    "userCode": "TEST-1234",
                }
            assert method == "account/login/cancel"
            assert params == {"loginId": "session-id"}

        def receive(self, wait):
            if authorize.wait(0.02):
                (tmp_path / "auth.json").touch()
                return {"method": "account/login/completed", "params": {"loginId": "session-id", "success": True}}

    monkeypatch.setattr(web_login, "codex_home", lambda: tmp_path)
    monkeypatch.setattr(web_login, "find_codex", lambda _home: "codex" if installed else None)
    monkeypatch.setattr(web_login, "install_codex", install_cli)
    monkeypatch.setattr(web_login, "AppServer", Server)
    monkeypatch.setattr(web_login, "cached_account", lambda: {})
    monkeypatch.setattr(web_login, "clear_model_cache", lambda: calls.append("clear"))
    monkeypatch.setattr(web_login, "refresh_models", lambda: calls.append("refresh"))

    setup = web_login.CodexSetup()
    setup.dispatch("login")
    pending = _wait_for(setup, "waiting")
    assert pending["installed"] and pending["user_code"] == "TEST-1234"
    setup.dispatch("login")  # Duplicate browser clicks reuse the pending authorization.
    if cancel:
        setup.dispatch("cancel")
    else:
        authorize.set()
    state = _wait_for(setup, "idle")
    assert state["signed_in"] is not cancel
    assert "user_code" not in state
    assert calls == (
        ["install", "account/login/start", "account/login/cancel", "close"] if cancel
        else ["install", "account/login/start", "clear", "close", "refresh"]
    )
