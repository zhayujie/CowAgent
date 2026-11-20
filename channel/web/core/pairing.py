"""One-time codes that let a new device sign in without the password.

A signed-in client asks for a code and shows it as a QR code (carrying a long
secret) and as a short code to type. Either one can be redeemed once, within a
few minutes, for a device token. Codes live in memory only: a restart simply
voids the ones outstanding.
"""

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from common.utils import constant_time_equals

TTL_SECONDS = 300
MAX_ACTIVE = 3
# No 0/O, 1/I/L: read off one screen and typed on another.
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
SHORT_LEN = 8


@dataclass
class Pairing:
    id: str
    secret: str
    code: str
    expires_at: float
    device: Optional[dict] = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def status(self) -> str:
        if self.device is not None:
            return "paired"
        return "expired" if self.expired else "pending"


_lock = threading.Lock()
_pairings: Dict[str, Pairing] = {}


def _short_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(SHORT_LEN))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _prune(now: float) -> None:
    # Paired and expired ones are kept a while so their creator can still
    # read the outcome.
    for pid in [pid for pid, p in _pairings.items() if now >= p.expires_at + TTL_SECONDS]:
        _pairings.pop(pid, None)


def create() -> Pairing:
    now = time.time()
    pairing = Pairing(
        id="p_" + secrets.token_hex(8),
        secret=secrets.token_urlsafe(24),
        code=_short_code(),
        expires_at=now + TTL_SECONDS,
    )
    with _lock:
        _prune(now)
        pending = sorted(
            (p for p in _pairings.values() if p.status() == "pending"),
            key=lambda p: p.expires_at,
        )
        for stale in pending[: max(0, len(pending) - MAX_ACTIVE + 1)]:
            _pairings.pop(stale.id, None)
        _pairings[pairing.id] = pairing
    return pairing


def get(pairing_id: str) -> Optional[Pairing]:
    with _lock:
        return _pairings.get(pairing_id)


def claim(code: str) -> Optional[Pairing]:
    """Take a pending pairing by its secret or short code; it can't be claimed again."""
    raw = str(code or "").strip()
    short = normalize_code(raw)
    with _lock:
        for pairing in _pairings.values():
            if pairing.status() != "pending":
                continue
            if constant_time_equals(raw, pairing.secret) or (
                len(short) == SHORT_LEN and constant_time_equals(short, pairing.code)
            ):
                # Spent before the device exists, so a second redeem racing
                # this one finds nothing.
                pairing.expires_at = 0
                return pairing
    return None


def complete(pairing: Pairing, device: dict) -> None:
    with _lock:
        pairing.device = device
        pairing.expires_at = time.time()


def reset() -> None:
    with _lock:
        _pairings.clear()
