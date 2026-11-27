"""Skip ``time.sleep`` for the calling test's thread only.

Patching ``"<module>.time.sleep"`` replaces ``sleep`` on the shared ``time``
module, so every thread sees it. Background threads left by earlier tests
(``ChatChannel``'s consumer loop sleeps 0.2s per tick) then spin at full speed,
and a stub that records its calls grows without bound until the run stalls.
"""

import threading
import time


def current_thread_sleep(record=None):
    """Return a ``sleep`` that returns at once on this thread and really sleeps
    on any other. Calls made on this thread are appended to ``record``."""
    real_sleep = time.sleep
    owner = threading.get_ident()

    def _sleep(seconds=0, *args, **kwargs):
        if threading.get_ident() != owner:
            return real_sleep(seconds)
        if record is not None:
            record.append(seconds)

    return _sleep


def stub_sleep(monkeypatch, record=None):
    """Install :func:`current_thread_sleep` as ``time.sleep``; return the record."""
    record = [] if record is None else record
    monkeypatch.setattr(time, "sleep", current_thread_sleep(record))
    return record
