# encoding:utf-8
"""
Regression tests for a dropped Playwright driver connection.

Once the driver connection drops, every further Playwright sync call on the
owning thread never returns and keeps a core busy. These tests make sure the
browser service stops calling into Playwright at that point, and that a thread
``close()`` gave up on cannot resume after a replacement thread is started.

No real browser is used: Playwright handles are replaced with stubs whose
``close()`` records the call, and the connection state is simulated through
the transport's ``on_error_future``.
"""
import os
import queue
import sys
import threading
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.browser.browser_service import BrowserService  # noqa: E402


class _Future:
    def __init__(self, done=False):
        self._done = done

    def done(self):
        return self._done


class _Handle:
    def __init__(self, on_close=None):
        self.closed = 0
        self._on_close = on_close

    def close(self):
        self.closed += 1
        if self._on_close:
            self._on_close()


class _Playwright:
    def __init__(self, lost=False):
        self.future = _Future(lost)
        transport = SimpleNamespace(on_error_future=self.future)
        self._impl_obj = SimpleNamespace(_connection=SimpleNamespace(_transport=transport))
        self.stopped = 0

    def stop(self):
        self.stopped += 1


def _service():
    svc = BrowserService({"cdp_endpoint": "http://127.0.0.1:9"})
    svc._launch_mode = "persistent"
    svc._idle_timeout = 0
    return svc


def _submit_raw(svc, fn):
    slot = {"event": threading.Event()}
    svc._task_queue.put((fn, (), {}, slot))
    return slot


class DriverConnectionLostTest(unittest.TestCase):
    def test_shutdown_skips_playwright_calls_after_connection_lost(self):
        svc = _service()
        pw = _Playwright(lost=True)
        ctx = _Handle()
        svc._playwright, svc._context = pw, ctx

        svc._shutdown_browser()

        self.assertEqual(ctx.closed, 0)
        self.assertEqual(pw.stopped, 1)
        self.assertIsNone(svc._playwright)
        self.assertIsNone(svc._context)

    def test_shutdown_stops_after_the_close_that_surfaces_the_loss(self):
        svc = _service()
        pw = _Playwright(lost=False)
        # The driver died while idle: the first close is what notices it.
        ctx = _Handle(on_close=lambda: setattr(pw.future, "_done", True))
        browser = _Handle()
        svc._playwright, svc._context, svc._browser = pw, ctx, browser

        svc._shutdown_browser()

        self.assertEqual(ctx.closed, 1)
        self.assertEqual(browser.closed, 0)
        self.assertEqual(pw.stopped, 1)

    def test_shutdown_closes_normally_while_connected(self):
        svc = _service()
        pw = _Playwright(lost=False)
        ctx, browser = _Handle(), _Handle()
        svc._playwright, svc._context, svc._browser = pw, ctx, browser

        svc._shutdown_browser()

        self.assertEqual((ctx.closed, browser.closed, pw.stopped), (1, 1, 1))

    def _start_loop(self, svc, pw):
        svc._launch_browser = lambda: setattr(svc, "_playwright", pw)
        svc._task_queue = queue.Queue()
        svc._alive = True
        svc._ready = threading.Event()
        svc._thread = threading.Thread(target=svc._run_loop, daemon=True)
        svc._thread.start()
        self.assertTrue(svc._ready.wait(5))

    def test_loop_exits_and_rejects_work_once_connection_is_lost(self):
        svc = _service()
        pw = _Playwright(lost=False)
        self._start_loop(svc, pw)
        ran = []

        def losing_task():
            pw.future._done = True
            return {"error": "Navigation failed: Connection closed while reading from the driver"}

        first = _submit_raw(svc, losing_task)
        self.assertTrue(first["event"].wait(5))
        second = _submit_raw(svc, lambda: ran.append(1))

        self.assertTrue(second["event"].wait(5))
        self.assertIn("error", second)
        self.assertEqual(ran, [])
        self.assertTrue(svc._needs_restart)

        thread = svc._thread
        svc.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(pw.stopped, 1)

    def test_abandoned_thread_does_not_resume_or_touch_replacement(self):
        svc = _service()
        pw = _Playwright(lost=False)
        release = threading.Event()
        self._start_loop(svc, pw)
        old = svc._thread

        blocked = _submit_raw(svc, lambda: release.wait(5))
        # What close() leaves behind after giving up on a stuck thread, followed
        # by a replacement thread setting _alive again.
        replacement_ctx = _Handle()
        svc._thread = threading.Thread(target=lambda: None)
        svc._alive = True
        svc._context = replacement_ctx
        release.set()
        self.assertTrue(blocked["event"].wait(5))
        old.join(5)

        self.assertFalse(old.is_alive())
        self.assertEqual(replacement_ctx.closed, 0)
        self.assertEqual(pw.stopped, 0)


if __name__ == "__main__":
    unittest.main()
