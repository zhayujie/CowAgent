# encoding:utf-8
"""
Unit tests for common/token_bucket.py.

Covers:
  - the generator thread is a daemon, so a bucket left open (which is what both
    production call sites do) cannot keep the process from exiting
  - a sub-1 tokens-per-minute config does not kill the generator thread with a
    ZeroDivisionError
  - a normal rate still hands out tokens
"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.token_bucket import TokenBucket

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestTokenBucket(unittest.TestCase):
    def test_generator_thread_is_a_daemon(self):
        """A rate limiter must never hold the process open at exit."""
        bucket = TokenBucket(20, 1)
        try:
            self.assertTrue(bucket._thread.daemon)
        finally:
            bucket.close()

    def test_process_exits_with_an_open_bucket(self):
        """Reproduces the production shape: build a bucket, never close it.

        With a non-daemon generator this subprocess would still be running when
        the timeout expires, and the interpreter would need a second signal.
        """
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from common.token_bucket import TokenBucket\n"
            "TokenBucket(20, None)\n"
            "print('constructed', flush=True)\n" % REPO_ROOT
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            out, _ = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            self.fail("process did not exit; the generator thread blocked shutdown")
        self.assertIn("constructed", out)
        self.assertEqual(process.returncode, 0)

    def test_sub_one_rate_does_not_break_the_generator(self):
        """A fractional tokens-per-minute must not raise ZeroDivisionError.

        int(0.5) is 0, so the per-second rate is 0.0 and the old
        ``time.sleep(1 / self.rate)`` raised, killing the thread silently and
        leaving every later get_token() to wait out its full timeout.
        """
        bucket = TokenBucket(0.5, timeout=0.5)
        time.sleep(0.3)

        self.assertLessEqual(bucket.rate, 0.0)
        # The generator stopped on purpose and said so, rather than dying.
        self.assertFalse(bucket.is_running)
        # Still reports a refusal rather than handing out a token it never made.
        self.assertFalse(bucket.get_token())

    def test_normal_rate_still_hands_out_tokens(self):
        bucket = TokenBucket(20, timeout=5)
        try:
            self.assertTrue(bucket.get_token())
        finally:
            bucket.close()

    def test_close_stops_the_generator_without_blocking(self):
        """close() signals the generator and returns promptly.

        The generator sleeps for 1/rate between tokens, so it may still be
        asleep when close() returns. What close() must guarantee is that it
        signals a stop and does not wait for that sleep - and that a missed
        join can never delay process exit, because the thread is a daemon.
        """
        bucket = TokenBucket(20, 1)
        started = time.monotonic()
        bucket.close()
        elapsed = time.monotonic() - started

        self.assertFalse(bucket.is_running)
        # Well under one refill interval, so close() is not waiting it out.
        self.assertLess(elapsed, 60 / bucket.rate)
        self.assertTrue(bucket._thread.daemon)


if __name__ == "__main__":
    unittest.main()
