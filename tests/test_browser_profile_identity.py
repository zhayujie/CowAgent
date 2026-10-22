"""Process discovery compares real argv without launching or controlling Chrome."""

import subprocess
import sys

import pytest

psutil = pytest.importorskip("psutil")

from agent.tools.browser.chrome_launcher import ChromeLauncher  # noqa: E402 (optional dependency gate)


@pytest.mark.skipif(sys.platform == "win32", reason="profile discovery is POSIX only")
@pytest.mark.parametrize("suffix", ["", "-backup", " other", " --fake-option"])
@pytest.mark.parametrize("profile_name", ["profile with spaces", "profile --type=literal"])
def test_native_process_discovery_matches_complete_profile(tmp_path, monkeypatch, suffix, profile_name):
    profile = str(tmp_path / profile_name)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)",
         "--remote-debugging-port=9999", f"--user-data-dir={profile}{suffix}", "--no-first-run"]
    )
    try:
        # Limit enumeration to our own child, while status/cmdline use actual
        # native psutil calls. No user browser, debugger or account is touched.
        process = psutil.Process(child.pid)
        monkeypatch.setattr(psutil, "process_iter", lambda: iter([process]))
        occupants = ChromeLauncher("unused", profile)._profile_chrome_processes()
        assert occupants == ([(child.pid, 9999)] if not suffix else [])
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="profile discovery is POSIX only")
def test_exited_candidate_is_ignored(monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    process = psutil.Process(child.pid)
    child.wait(timeout=5)
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([process]))
    assert ChromeLauncher("unused", "unused")._profile_chrome_processes() == []


@pytest.mark.skipif(sys.platform == "win32", reason="profile discovery is POSIX only")
def test_denied_candidate_is_ignored(monkeypatch):
    process = psutil.Process()
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([process]))

    def denied():
        raise psutil.AccessDenied(process.pid)

    monkeypatch.setattr(process, "cmdline", denied)
    assert ChromeLauncher("unused", "unused")._profile_chrome_processes() == []


@pytest.mark.skipif(sys.platform == "win32", reason="profile discovery is POSIX only")
@pytest.mark.parametrize("case", ["last_other", "last_expected", "after_terminator", "renderer", "unicode_port"])
def test_native_option_boundaries(tmp_path, monkeypatch, case):
    profile = str(tmp_path / "profile")
    expected = f"--user-data-dir={profile}"
    other = f"--user-data-dir={profile}-other"
    flags = {
        "last_other": [expected, other],
        "last_expected": [other, "--remote-debugging-port=1111", expected],
        "after_terminator": [other, "--", expected],
        "renderer": [expected, "--type=renderer"],
        "unicode_port": [expected],
    }[case]
    flags += ["--remote-debugging-port=" + ("９９９９" if case == "unicode_port" else "9999")]
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *flags])
    try:
        process = psutil.Process(child.pid)
        monkeypatch.setattr(psutil, "process_iter", lambda: iter([process]))
        occupants = ChromeLauncher("unused", profile)._profile_chrome_processes()
        expected_occupants = {"last_expected": [(child.pid, 9999)], "unicode_port": [(child.pid, None)]}
        assert occupants == expected_occupants.get(case, [])
    finally:
        child.terminate()
        child.wait(timeout=5)
