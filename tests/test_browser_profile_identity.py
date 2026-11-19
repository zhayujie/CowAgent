"""Identify profile occupants using native ps without a new dependency."""

import builtins
import subprocess
import sys

import pytest

from agent.tools.browser.chrome_launcher import ChromeLauncher


@pytest.mark.skipif(sys.platform == "win32", reason="profile discovery is POSIX only")
@pytest.mark.parametrize("profile_name", ["profile", "profile with spaces"])
@pytest.mark.parametrize("case", ["exact_end", "exact_middle", "sibling", "renderer"])
def test_native_process_discovery_matches_profile_boundary(tmp_path, monkeypatch, profile_name, case):
    monkeypatch.setenv("COLUMNS", "80")
    # Long values expose process-list truncation on GNU ps.
    profile = str(tmp_path / ("long-profile-" * 8) / profile_name)
    value = profile + ("-backup" if case == "sibling" else "")
    flags = ["--remote-debugging-port=9999", f"--user-data-dir={value}"]
    if case == "exact_middle":
        flags.append("--no-first-run")
    if case == "renderer":
        flags.append("--type=renderer")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *flags])
    try:
        # Only a harmless task-owned sleeper is spawned; the launcher reads
        # real ps output without attaching to or controlling any browser.
        occupants = ChromeLauncher("unused", profile)._profile_chrome_processes()
        assert occupants == ([(child.pid, 9999)] if case.startswith("exact") else [])
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_profile_discovery_does_not_require_psutil(tmp_path, monkeypatch):
    original_import = builtins.__import__

    def without_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ModuleNotFoundError("psutil is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_psutil)
    assert ChromeLauncher("unused", str(tmp_path / "unused"))._profile_chrome_processes() == []
