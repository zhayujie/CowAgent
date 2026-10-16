"""The win32 pid probe must carry a timeout and degrade like the posix branch.

_pid_alive runs on the terminate and adopt paths of the browser tool. Its
win32 branch called tasklist with neither a timeout nor an except, while
every other subprocess call in the file (the posix ps probe, taskkill, the
profile scan) has both. A hung tasklist wedged the caller forever and a
missing one raised out of terminate.
"""

import subprocess
import unittest
from unittest.mock import patch

from agent.tools.browser.chrome_launcher import ChromeLauncher


class _FakeCompleted:
    def __init__(self, stdout):
        self.stdout = stdout


class ChromeLauncherPidAliveTest(unittest.TestCase):

    @patch("agent.tools.browser.chrome_launcher.sys")
    def test_win32_probe_passes_a_timeout(self, fake_sys):
        fake_sys.platform = "win32"
        seen = {}

        def fake_run(cmd, **kwargs):
            seen.update(kwargs)
            return _FakeCompleted('"1234"\r\n')

        with patch.object(subprocess, "run", fake_run):
            alive = ChromeLauncher._pid_alive(1234)

        self.assertTrue(alive)
        self.assertIn("timeout", seen, "tasklist probe ran without a timeout")

    @patch("agent.tools.browser.chrome_launcher.sys")
    def test_win32_probe_survives_a_hung_tasklist(self, fake_sys):
        fake_sys.platform = "win32"

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd="tasklist", timeout=kwargs.get("timeout", 5))

        with patch.object(subprocess, "run", fake_run):
            # A probe we cannot finish must not raise out of terminate/adopt;
            # treat the pid as alive, the way the posix branch does.
            alive = ChromeLauncher._pid_alive(1234)

        self.assertTrue(alive)

    @patch("agent.tools.browser.chrome_launcher.sys")
    def test_win32_probe_survives_a_missing_tasklist(self, fake_sys):
        fake_sys.platform = "win32"

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("tasklist not on PATH")

        with patch.object(subprocess, "run", fake_run):
            alive = ChromeLauncher._pid_alive(1234)

        self.assertTrue(alive)

    @patch("agent.tools.browser.chrome_launcher.sys")
    def test_win32_probe_reports_a_dead_pid(self, fake_sys):
        fake_sys.platform = "win32"

        def fake_run(cmd, **kwargs):
            return _FakeCompleted("INFO: No tasks are running which match the specified criteria.\r\n")

        with patch.object(subprocess, "run", fake_run):
            alive = ChromeLauncher._pid_alive(1234)

        self.assertFalse(alive)

    @patch("agent.tools.browser.chrome_launcher.sys")
    def test_posix_probe_reports_zombie_state(self, fake_sys):
        fake_sys.platform = "linux"
        import os

        def fake_run(cmd, **kwargs):
            self.assertIn("timeout", kwargs, "posix ps probe lost its timeout")
            return _FakeCompleted("Z\n")

        with patch.object(os, "kill", lambda pid, sig: None), \
                patch.object(subprocess, "run", fake_run):
            alive = ChromeLauncher._pid_alive(os.getpid())

        self.assertFalse(alive, "a zombie pid must not count as alive")


if __name__ == "__main__":
    unittest.main()
