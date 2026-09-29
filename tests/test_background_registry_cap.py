"""
Tests that the background job registry stays bounded.

The module promises the registry "must not grow forever", but eviction used to
be a no-op whenever every tracked job was still running. That is precisely the
burst of concurrent servers this registry exists to support, so each one leaked
a live Popen, an open stdout pipe and its output buffer for the process lifetime.
"""

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools.bash import background

# A python child rather than `sleep`/`ping`: no POSIX-only shell syntax, no
# dependency on `sleep` existing or on ICMP being allowed to loopback. Quoted
# so the path stays safe when the venv lives under "Program Files".
_STAYS_UP = '"%s" -c "import time; time.sleep(120)"' % sys.executable
_FINISHES = '"%s" -c "print(1)"' % sys.executable


class _Base(unittest.TestCase):
    def setUp(self):
        background.reset()
        self._spawned = []
        self._env = dict(os.environ)

    def tearDown(self):
        background.reset()
        # Evicted jobs are gone from the registry, so reset() can no longer
        # reach them. Hold the job objects ourselves and kill through them, or
        # this test leaks the processes it started.
        for job in self._spawned:
            if job.running:
                background._kill_process(job.process)
            job.process.wait(timeout=10)

    def _start(self, command):
        job_id = background.start(command, os.getcwd(), self._env)
        self._spawned.append(background._jobs[job_id])
        return job_id

    def _spawn(self, command):
        """Start a job and return the job object, for tests that outlive eviction."""
        self._start(command)
        return self._spawned[-1]

    def _wait_until_finished(self, jobs, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if all(not job.running for job in jobs):
                return
            time.sleep(0.05)
        self.fail("background jobs did not finish within %ss" % timeout)


class TestRegistryCap(_Base):
    def test_stays_capped_while_every_job_is_still_running(self):
        # More long-lived jobs than the cap allows, none of which can ever be
        # evicted as "finished" - the burst of servers this module exists for.
        jobs = [self._spawn(_STAYS_UP) for _ in range(background._MAX_JOBS + 5)]

        self.assertLessEqual(
            len(background._jobs),
            background._MAX_JOBS,
            "registry grew to %d jobs with every one of them still running"
            % len(background._jobs),
        )
        # The cap is enforced by dropping the oldest, so the survivors are the
        # newest and the five oldest ids no longer resolve.
        for stale in jobs[:5]:
            self.assertNotIn(stale.id, background._jobs)
        for kept in jobs[5:]:
            self.assertIn(kept.id, background._jobs)
        # An evicted job is forgotten, not killed: the module deliberately
        # leaves processes alone so a server the user asked for keeps serving.
        self.assertIsNone(
            jobs[0].process.poll(),
            "eviction must drop the bookkeeping, not the process",
        )
        self.assertIsNone(background.read(jobs[0].id), "an evicted id should not resolve")


class TestFinishedJobsStillEvictedOldestFirst(_Base):
    def test_finished_jobs_are_dropped_oldest_first(self):
        # The pre-existing behaviour, kept intact: a late poll should still find
        # the most recent finished jobs, so oldest goes before newest.
        jobs = [self._spawn(_FINISHES) for _ in range(background._MAX_JOBS + 3)]
        self._wait_until_finished(jobs)
        fresh = self._start(_FINISHES)

        self.assertEqual(len(background._jobs), background._MAX_JOBS)
        self.assertEqual(
            set(background._jobs),
            {j.id for j in jobs[4:]} | {fresh},
            "the four oldest finished jobs should have been dropped",
        )
        for stale in jobs[:4]:
            self.assertIsNone(background.read(stale.id))

    def test_finished_jobs_are_preferred_over_running_ones(self):
        # A job that starts last but exits immediately is newer than the long
        # servers, yet finished - it must be the one that gets dropped.
        running = [self._start(_STAYS_UP) for _ in range(background._MAX_JOBS - 1)]
        quick = self._spawn(_FINISHES)
        self._wait_until_finished([quick])

        self._start(_FINISHES)

        self.assertNotIn(quick.id, background._jobs, "a finished job should be evicted first")
        for kept in running:
            self.assertIn(kept, background._jobs, "running jobs should outrank a finished one")


if __name__ == "__main__":
    unittest.main()
