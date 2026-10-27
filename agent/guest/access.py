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


class LoginLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._client: Dict[Tuple[str, str], Deque[float]] = {}
        self._client_locked: Dict[Tuple[str, str], float] = {}
        self._profile: Dict[str, Deque[float]] = {}
        self._profile_locked: Dict[str, float] = {}

    def locked_for(self, slug: str, client: str, now: float = None) -> int:
        """Seconds until ``client`` may try a password on ``slug`` again (0 = now)."""
        now = now or time.time()
        with self._lock:
            until = max(self._client_locked.get((slug, client), 0), self._profile_locked.get(slug, 0))
        return max(0, int(until - now + 0.999))

    def failed(self, slug: str, client: str, now: float = None) -> None:
        now = now or time.time()
        with self._lock:
            key = (slug, client)
            hits = self._client.setdefault(key, deque())
            while hits and now - hits[0] > CLIENT_LOCK_SECONDS:
                hits.popleft()
            hits.append(now)
            if len(hits) >= MAX_FAILURES_PER_CLIENT:
                self._client_locked[key] = now + CLIENT_LOCK_SECONDS
                hits.clear()
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
