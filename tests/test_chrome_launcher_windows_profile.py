"""Find the Chrome holding our profile on Windows, so a leftover one is reused.

Chrome is spawned detached and outlives a backend restart. On Windows the
profile owner was never discovered (no SingletonLock symlink, no process
scan), so the next spawn handed its window to the leftover Chrome, exited
with code 0 and never opened its own debug port: the browser tool stayed
"not available" until the leftover was killed by hand.
"""

import base64
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent.tools.browser.chrome_launcher import ChromeLauncher

PROFILE = r"C:\Users\someone/.cow/browser_profile"
SPACED_PROFILE = r"C:\Users\some one/.cow/browser_profile"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class _FakeCompleted:
    def __init__(self, stdout):
        self.stdout = stdout


def _listing(*rows):
    return "\r\n".join(f"{pid}\t{command}" for pid, command in rows) + "\r\n"


@patch("agent.tools.browser.chrome_launcher.sys")
class WindowsProfileDiscoveryTest(unittest.TestCase):

    def test_free_profile_skips_the_process_scan(self, fake_sys):
        fake_sys.platform = "win32"
        launcher = ChromeLauncher(CHROME, PROFILE)
        with patch.object(launcher, "_windows_profile_in_use", return_value=False), \
                patch("agent.tools.browser.chrome_launcher.subprocess.run") as run:
            self.assertEqual(launcher._profile_chrome_processes(), [])
        run.assert_not_called()

    def test_finds_the_browser_process_and_its_port(self, fake_sys):
        fake_sys.platform = "win32"
        launcher = ChromeLauncher(CHROME, PROFILE)
        listing = _listing(
            (45200, f'"{CHROME}" --remote-debugging-port=60161 '
                    f"--user-data-dir={PROFILE} --no-first-run about:blank"),
            (45210, f'"{CHROME}" --type=renderer --user-data-dir={PROFILE}'),
            (45300, f'"{CHROME}" --remote-debugging-port=1234 '
                    f"--user-data-dir={PROFILE}-backup about:blank"),
            (45400, f'"{CHROME}"'),
        )
        with patch.object(launcher, "_windows_profile_in_use", return_value=True), \
                patch("agent.tools.browser.chrome_launcher.subprocess.run",
                      return_value=_FakeCompleted(listing)) as run:
            self.assertEqual(launcher._profile_chrome_processes(), [(45200, 60161)])
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "powershell")
        self.assertEqual(cmd[-2], "-EncodedCommand")
        self.assertIn("Name='chrome.exe'", base64.b64decode(cmd[-1]).decode("utf-16-le"))
        self.assertIn("timeout", run.call_args.kwargs)

    def test_matches_a_quoted_path_case_insensitively(self, fake_sys):
        fake_sys.platform = "win32"
        launcher = ChromeLauncher(CHROME, SPACED_PROFILE)
        listing = _listing(
            (7, f'"{CHROME}" --remote-debugging-port=50000 '
                f'"--user-data-dir={SPACED_PROFILE.upper()}" about:blank'),
        )
        with patch.object(launcher, "_windows_profile_in_use", return_value=True), \
                patch("agent.tools.browser.chrome_launcher.subprocess.run",
                      return_value=_FakeCompleted(listing)):
            self.assertEqual(launcher._profile_chrome_processes(), [(7, 50000)])

    def test_failed_scan_degrades_to_no_occupants(self, fake_sys):
        fake_sys.platform = "win32"
        launcher = ChromeLauncher(CHROME, PROFILE)
        with patch.object(launcher, "_windows_profile_in_use", return_value=True), \
                patch("agent.tools.browser.chrome_launcher.subprocess.run",
                      side_effect=subprocess.TimeoutExpired("powershell", 15)):
            self.assertEqual(launcher._profile_chrome_processes(), [])

    def test_launch_reuses_the_leftover_chrome(self, fake_sys):
        fake_sys.platform = "win32"
        launcher = ChromeLauncher(CHROME, PROFILE)
        with patch.object(launcher, "_windows_profile_processes",
                          return_value=[(45200, f"--remote-debugging-port=60161 "
                                                f"--user-data-dir={PROFILE}")]), \
                patch.object(launcher, "_cdp_reachable", return_value=True), \
                patch.object(launcher, "_spawn_and_wait") as spawn, \
                patch("agent.tools.browser.chrome_launcher.os.makedirs"):
            self.assertEqual(launcher.launch(), "http://127.0.0.1:60161")
        spawn.assert_not_called()
        self.assertTrue(launcher.adopted)

    def test_launch_stops_a_leftover_it_cannot_attach_to(self, fake_sys):
        fake_sys.platform = "win32"
        launcher = ChromeLauncher(CHROME, PROFILE)
        with patch.object(launcher, "_windows_profile_processes",
                          return_value=[(45200, f"--user-data-dir={PROFILE}")]), \
                patch.object(launcher, "_terminate_pid") as terminate, \
                patch.object(launcher, "_spawn_and_wait") as spawn, \
                patch("agent.tools.browser.chrome_launcher.os.makedirs"):
            launcher.launch()
        terminate.assert_called_once_with(45200)
        spawn.assert_called_once()


class WindowsProfileLockTest(unittest.TestCase):

    def test_missing_lockfile_means_free(self):
        with patch("agent.tools.browser.chrome_launcher.os.path.exists", return_value=False):
            self.assertFalse(ChromeLauncher(CHROME, PROFILE)._windows_profile_in_use())

    def test_sharing_violation_means_in_use(self):
        with patch("agent.tools.browser.chrome_launcher.os.path.exists", return_value=True), \
                patch("builtins.open", side_effect=PermissionError(13, "in use")):
            self.assertTrue(ChromeLauncher(CHROME, PROFILE)._windows_profile_in_use())

    def test_openable_lockfile_means_free(self):
        with tempfile.TemporaryDirectory() as profile:
            open(os.path.join(profile, "lockfile"), "w").close()
            self.assertFalse(ChromeLauncher(CHROME, profile)._windows_profile_in_use())


if __name__ == "__main__":
    unittest.main()
