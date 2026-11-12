"""Chrome profile locks.

The launcher used to delete Chrome's Singleton* locks unconditionally while
calling them stale. Our Chrome is spawned detached, so it outlives a service
restart - deleting its live lock put two browsers on one profile, which Chrome
reports as "something went wrong with your profile" and which leaves the
second one unable to open a debug port.
"""

import os

import pytest

from agent.tools.browser.chrome_launcher import ChromeLauncher

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process checks")


def _launcher(profile) -> ChromeLauncher:
    return ChromeLauncher("/nonexistent/chrome", str(profile))


def _write_locks(profile, owner: str):
    os.symlink(owner, profile / "SingletonLock")
    (profile / "SingletonCookie").write_text("cookie")
    (profile / "SingletonSocket").write_text("socket")


@posix_only
def test_a_live_owner_is_reported(tmp_path):
    _write_locks(tmp_path, f"myhost-{os.getpid()}")

    assert _launcher(tmp_path)._singleton_owner_pid() == os.getpid()


@posix_only
def test_a_dead_owner_reads_as_no_owner(tmp_path):
    # Well above the pid range that could be running.
    _write_locks(tmp_path, "myhost-4194303")

    assert _launcher(tmp_path)._singleton_owner_pid() is None


def test_no_lock_reads_as_no_owner(tmp_path):
    assert _launcher(tmp_path)._singleton_owner_pid() is None


def test_an_unparsable_lock_target_reads_as_no_owner(tmp_path):
    os.symlink("myhost-notapid", tmp_path / "SingletonLock")

    assert _launcher(tmp_path)._singleton_owner_pid() is None


@posix_only
def test_a_zombie_does_not_count_as_alive():
    """os.kill(pid, 0) succeeds for zombies, so state has to be checked."""
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    try:
        # Block until the child has exited, without reaping it: right after
        # fork() it may still be running, and ps would report it as alive.
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
        assert ChromeLauncher._pid_alive(pid) is False
    finally:
        os.waitpid(pid, 0)


def test_this_process_counts_as_alive():
    assert ChromeLauncher._pid_alive(os.getpid()) is True


def test_clearing_removes_every_lock(tmp_path):
    _write_locks(tmp_path, "myhost-4194303")

    _launcher(tmp_path)._clear_stale_singleton_locks()

    assert not list(tmp_path.glob("Singleton*"))


def test_devtools_port_is_read_from_the_profile(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("54321\n/devtools/browser/abc\n")

    assert _launcher(tmp_path)._devtools_active_port() == 54321


def test_missing_devtools_file_is_not_an_error(tmp_path):
    assert _launcher(tmp_path)._devtools_active_port() is None


@posix_only
def test_no_occupants_for_an_unused_profile(tmp_path):
    assert _launcher(tmp_path)._profile_chrome_processes() == []


def test_a_fresh_launcher_has_not_adopted_anything(tmp_path):
    assert _launcher(tmp_path).adopted is False


@posix_only
def test_adoption_can_be_declined(tmp_path, monkeypatch):
    """An adopted browser can turn out to be unattachable, so callers need a
    way to insist on a new one rather than reusing the same broken instance."""
    launcher = _launcher(tmp_path)
    monkeypatch.setattr(launcher, "_profile_chrome_processes", lambda: [(4242, 9222)])
    monkeypatch.setattr(launcher, "_cdp_reachable", lambda port: True)
    monkeypatch.setattr(launcher, "_singleton_owner_pid", lambda: None)
    terminated = []
    monkeypatch.setattr(launcher, "_terminate_pid", terminated.append)
    monkeypatch.setattr(launcher, "_spawn_and_wait", lambda timeout: None)

    launcher.launch(adopt=False)

    assert launcher.adopted is False
    assert terminated == [4242]
