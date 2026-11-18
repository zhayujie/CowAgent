"""Rate-limiter buckets must not pin the process-wide dicts forever.

GuestPages._ip_hits and LoginLimiter._client keyed by client IP/id only ever
shrank via popleft when the *same* key came back — an attacker (or just a
long tail of one-shot visitors) rotating keys left an empty bucket behind
forever, so the dicts grew monotonically for the process lifetime. The
password and guest endpoints are unauthenticated, and behind a reverse proxy
the key comes from X-Forwarded-For, so the key space is attacker-chosen.
Both classes now sweep once the dicts pass a threshold; these tests pin the
sweep keeping live buckets and dropping dead ones.
"""
import os
import sys
import time
import unittest
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.guest.access import LoginLimiter, _CLIENT_SWEEP_THRESHOLD
from channel.web.core.guest_pages import GuestPages, _IP_HITS_SWEEP_THRESHOLD


class TestGuestPagesSweep(unittest.TestCase):

    def test_stale_buckets_are_dropped_and_live_ones_kept(self):
        # Timestamps are taken here, not at module import: allow_ip() reads
        # the wall clock itself, and in a full-suite run minutes can pass
        # between collection and this test — an import-time "fresh" hit would
        # then be stale already and the assertion below would flake.
        now = time.time()
        pages = GuestPages()
        pages._ip_hits = {f"msg:1.2.3.{i}": deque([now - 120]) for i in range(_IP_HITS_SWEEP_THRESHOLD + 8)}
        pages._ip_hits["msg:live"] = deque([now - 5])

        pages.allow_ip("msg:new", 5)

        self.assertIn("msg:live", pages._ip_hits)
        self.assertIn("msg:new", pages._ip_hits)
        self.assertNotIn("msg:1.2.3.0", pages._ip_hits)
        self.assertLess(len(pages._ip_hits), 5, "stale buckets survived the sweep")

    def test_below_the_threshold_nothing_is_swept(self):
        now = time.time()
        pages = GuestPages()
        pages._ip_hits = {f"msg:x{i}": deque([now - 120]) for i in range(10)}

        pages.allow_ip("msg:new", 5)

        # Small dicts are left alone; the sweep only exists to bound growth.
        self.assertEqual(len(pages._ip_hits), 11)


class TestLoginLimiterSweep(unittest.TestCase):

    def test_stale_client_buckets_and_expired_locks_are_dropped(self):
        now = time.time()
        limiter = LoginLimiter()
        limiter._client = {
            ("slug", f"c{i}"): deque([now - 5000]) for i in range(_CLIENT_SWEEP_THRESHOLD + 8)
        }
        limiter._client_locked = {
            ("slug", "still-locked"): now + 100,
            ("slug", "expired"): now - 100,
        }

        limiter.failed("slug", "fresh", now=now)

        self.assertIn(("slug", "fresh"), limiter._client)
        self.assertIn(("slug", "still-locked"), limiter._client_locked)
        self.assertNotIn(("slug", "expired"), limiter._client_locked)
        self.assertNotIn(("slug", "c0"), limiter._client)
        self.assertLess(len(limiter._client), 5, "stale buckets survived the sweep")

    def test_lockout_behavior_is_unchanged_below_the_threshold(self):
        now = time.time()
        limiter = LoginLimiter()
        for _ in range(5):
            limiter.failed("slug", "attacker", now=now)
        self.assertGreater(limiter.locked_for("slug", "attacker", now=now), 0)
        self.assertEqual(limiter.locked_for("slug", "other", now=now), 0)


if __name__ == "__main__":
    unittest.main()
