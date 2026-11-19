"""Throttling for the unauthenticated guest endpoints.

Password guessing is limited per client and per profile: a client is locked
out after a few wrong passwords, and a profile stops accepting passwords for a
while once wrong ones arrive from many clients at once, so rotating addresses
does not buy unlimited guesses. Counters live in memory; a restart resets
them, which costs an attacker a restart they cannot trigger.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

MAX_FAILURES_PER_CLIENT = 5
CLIENT_LOCK_SECONDS = 600
MAX_FAILURES_PER_PROFILE = 30
PROFILE_WINDOW_SECONDS = 3600
PROFILE_LOCK_SECONDS = 900

# Rebuild the per-client dicts once they grow past this size, keeping only
# live buckets. The password endpoints are unauthenticated and the keys carry
# client ids an attacker forges, so without a sweep every distinct attacker
# key pins a bucket (or an expired lock entry) for the process lifetime.
# _profile stays unswept: it is keyed by profile slug, a small fixed set.
_CLIENT_SWEEP_THRESHOLD = 1024
# At most one rebuild per interval: without it a flood turns the sweep into
# per-call CPU amplification under the global lock.
_CLIENT_SWEEP_INTERVAL = 60.0


class LoginLimiter:
    def __init__(self, per_profile: bool = True):
        self._per_profile = per_profile
        self._lock = threading.Lock()
        self._client: Dict[Tuple[str, str], Deque[float]] = {}
        self._client_locked: Dict[Tuple[str, str], float] = {}
        self._profile: Dict[str, Deque[float]] = {}
        self._profile_locked: Dict[str, float] = {}
        self._last_sweep = 0.0

    def locked_for(self, slug: str, client: str, now: float = None) -> int:
        """Seconds until ``client`` may try a password on ``slug`` again (0 = now)."""
        now = now or time.time()
        with self._lock:
            until = max(self._client_locked.get((slug, client), 0), self._profile_locked.get(slug, 0))
        return max(0, int(until - now + 0.999))

    def _sweep_expired(self, now: float) -> None:
        """Drop stale per-client state (caller holds the lock), at most once
        per interval (see _CLIENT_SWEEP_INTERVAL)."""
        if len(self._client) < _CLIENT_SWEEP_THRESHOLD:
            return
        if now - self._last_sweep < _CLIENT_SWEEP_INTERVAL:
            return
        self._last_sweep = now
        self._client = {
            key: hits for key, hits in self._client.items()
            if hits and now - hits[-1] <= CLIENT_LOCK_SECONDS
        }
        self._client_locked = {
            key: until for key, until in self._client_locked.items()
            if until > now
        }

    def failed(self, slug: str, client: str, now: float = None) -> None:
        now = now or time.time()
        with self._lock:
            self._sweep_expired(now)
            key = (slug, client)
            hits = self._client.setdefault(key, deque())
            while hits and now - hits[0] > CLIENT_LOCK_SECONDS:
                hits.popleft()
            hits.append(now)
            if len(hits) >= MAX_FAILURES_PER_CLIENT:
                self._client_locked[key] = now + CLIENT_LOCK_SECONDS
                hits.clear()
            if not self._per_profile:
                return
            profile_hits = self._profile.setdefault(slug, deque())
            while profile_hits and now - profile_hits[0] > PROFILE_WINDOW_SECONDS:
                profile_hits.popleft()
            profile_hits.append(now)
            if len(profile_hits) >= MAX_FAILURES_PER_PROFILE:
                self._profile_locked[slug] = now + PROFILE_LOCK_SECONDS
                profile_hits.clear()

    def succeeded(self, slug: str, client: str) -> None:
        with self._lock:
            self._client.pop((slug, client), None)
            self._client_locked.pop((slug, client), None)

    def reset(self, slug: str) -> None:
        with self._lock:
            for key in [k for k in self._client if k[0] == slug]:
                self._client.pop(key, None)
            for key in [k for k in self._client_locked if k[0] == slug]:
                self._client_locked.pop(key, None)
            self._profile.pop(slug, None)
            self._profile_locked.pop(slug, None)


login_limiter = LoginLimiter()
