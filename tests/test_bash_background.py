"""
Tests for background execution and timeout handling in the bash tool.

Background support exists because the model was otherwise hand-rolling it -
`nohup cmd &`, echo the PID, `sleep 1`, then curl to check - which is verbose
and races the process startup.
"""

import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools.bash.bash import Bash
from agent.tools.bash import background

IS_WIN = sys.platform == "win32"


@unittest.skipIf(IS_WIN, "POSIX shell syntax")
class _Base(unittest.TestCase):
    def setUp(self):
        background.reset()
        self._tmp = TemporaryDirectory()
        self.tool = Bash({"cwd": self._tmp.name})

    def tearDown(self):
        background.reset()
        self._tmp.cleanup()

    def _start(self, command):
        result = self.tool.execute({"command": command, "run_in_background": True})
        self.assertEqual(result.status, "success")
        return result.result["bash_id"]

    def _wait_until_done(self, job_id, timeout=5):
        deadline = time.time() + timeout
        collected = ""
        while time.time() < deadline:
            result = self.tool.execute({"bash_id": job_id})
            collected += result.result["output"]
            if not result.result["running"]:
                return result, collected
            time.sleep(0.1)
        self.fail(f"background job {job_id} did not finish in {timeout}s")


class TestBackgroundLifecycle(_Base):
    def test_start_returns_immediately_with_an_id(self):
        started = time.monotonic()
        result = self.tool.execute({"command": "sleep 30", "run_in_background": True})
        self.assertLess(time.monotonic() - started, 5, "start should not block on the command")
        self.assertEqual(result.status, "success")
        self.assertTrue(result.result["bash_id"].startswith("bash_"))

    def test_result_tells_the_model_how_to_follow_up(self):
        result = self.tool.execute({"command": "sleep 30", "run_in_background": True})
        self.assertIn(result.result["bash_id"], result.result["output"])
        self.assertIn("kill=true", result.result["output"])

    def test_reads_only_output_since_the_last_look(self):
        job = self._start("echo first; sleep 1; echo second")
        time.sleep(0.4)
        first = self.tool.execute({"bash_id": job}).result["output"]
        self.assertIn("first", first)
        self.assertNotIn("second", first)

        _, rest = self._wait_until_done(job)
        self.assertIn("second", rest)
        self.assertNotIn("first", rest, "already-read output must not repeat")

    def test_reports_exit_code_when_finished(self):
        job = self._start("echo done")
        result, _ = self._wait_until_done(job)
        self.assertFalse(result.result["running"])
        self.assertEqual(result.result["exit_code"], 0)

    def test_nonzero_exit_is_reported_as_a_failure(self):
        job = self._start("echo oops; exit 3")
        result, output = self._wait_until_done(job)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.result["exit_code"], 3)
        self.assertIn("oops", output)

    def test_kill_stops_a_running_job(self):
        job = self._start("sleep 300")
        self.assertTrue(background.read(job)["running"])

        result = self.tool.execute({"bash_id": job, "kill": True})
        self.assertEqual(result.status, "success")
        self.assertFalse(background.read(job)["running"])

    def test_kill_reaches_children_not_just_the_shell(self):
        # The command is a shell that spawns sleep; killing only the shell
        # would leave the child running.
        job = self._start("sleep 300 & wait")
        time.sleep(0.3)
        self.tool.execute({"bash_id": job, "kill": True})
        self.assertFalse(background.read(job)["running"])

    def test_stderr_is_captured_too(self):
        job = self._start("echo to-stderr >&2")
        _, output = self._wait_until_done(job)
        self.assertIn("to-stderr", output)


class TestUnknownJob(_Base):
    def test_unknown_id_is_an_error_that_lists_what_exists(self):
        live = self._start("sleep 30")
        result = self.tool.execute({"bash_id": "bash_missing"})
        self.assertEqual(result.status, "error")
        self.assertIn(live, str(result.result))

    def test_unknown_id_with_nothing_tracked_says_so(self):
        result = self.tool.execute({"bash_id": "bash_missing"})
        self.assertEqual(result.status, "error")
        self.assertIn("none are being tracked", str(result.result))


class TestTimeout(_Base):
    def test_default_is_generous_enough_for_installs(self):
        # 30s used to time out routine package installs, costing a retry.
        self.assertEqual(self.tool.default_timeout, 120)

    def test_over_the_cap_points_at_background_instead(self):
        result = self.tool.execute({"command": "echo x", "timeout": 9999})
        self.assertEqual(result.status, "error")
        self.assertIn("run_in_background", str(result.result))

    def test_rejects_a_non_integer(self):
        result = self.tool.execute({"command": "echo x", "timeout": "abc"})
        self.assertEqual(result.status, "error")

    def test_foreground_still_works(self):
        result = self.tool.execute({"command": "echo hi"})
        self.assertEqual(result.status, "success")
        self.assertIn("hi", result.result["output"])

    def test_command_is_still_required_without_a_bash_id(self):
        result = self.tool.execute({})
        self.assertEqual(result.status, "error")
        self.assertIn("command parameter is required", str(result.result))


if __name__ == "__main__":
    unittest.main()
