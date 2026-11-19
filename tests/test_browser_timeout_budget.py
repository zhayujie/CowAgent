"""A model-supplied timeout must not outlive what the caller will wait for.

``_submit`` stops waiting after a fixed budget, but the single browser worker
thread stays inside the Playwright call for as long as the model asked, and
every later action queues behind it. Model timeouts are therefore clamped
below the budget; ``0`` (Playwright's "no timeout") maps to the ceiling and
``None`` or junk falls back to the action's default.
"""

import queue
import threading

import pytest

from agent.tools.browser import browser_service
from agent.tools.browser.browser_service import BrowserService

CEILING = browser_service._MODEL_TIMEOUT_CEILING_MS


class _RecordingPage:
    """A page that remembers the timeouts Playwright was handed."""

    def __init__(self):
        self.goto_timeouts = []
        self.sleeps = []
        self.selector_timeouts = []
        self.click_timeouts = []
        self.fill_timeouts = []
        self.select_timeouts = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_timeouts.append(timeout)
        return None

    def wait_for_load_state(self, state, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        self.sleeps.append(ms)

    def wait_for_selector(self, selector, timeout=None, state=None):
        self.selector_timeouts.append(timeout)

    def click(self, selector, timeout=None):
        self.click_timeouts.append(timeout)

    def fill(self, selector, text, timeout=None):
        self.fill_timeouts.append(timeout)

    def select_option(self, selector, value, timeout=None):
        self.select_timeouts.append(timeout)

    def title(self):
        return ""

    @property
    def url(self):
        return "https://example.com/"


def _a_service_with(page):
    """A service whose actions run inline against *page*.

    ``__new__`` skips ``__init__`` (it would launch a browser), and the
    ``_submit`` stand-in dispatches straight to the ``_do_*`` method instead
    of queueing for the background thread -- the clamp lives on the public
    method, so what the page records is what Playwright would receive.
    """
    service = BrowserService.__new__(BrowserService)
    service._page = page
    service._submit = lambda fn, *a, **k: fn(*a, **k)
    return service


def test_navigate_clamps_a_model_timeout_to_the_submit_budget():
    page = _RecordingPage()

    _a_service_with(page).navigate("https://slow.example.com", timeout=600_000)

    assert page.goto_timeouts == [CEILING]


def test_wait_without_a_selector_clamps_the_sleep():
    page = _RecordingPage()

    _a_service_with(page).wait(timeout=3_600_000)

    assert page.sleeps == [CEILING]


def test_click_clamps_a_model_timeout_to_the_submit_budget():
    page = _RecordingPage()

    _a_service_with(page).click(selector="#buy", timeout=600_000)

    assert page.click_timeouts == [CEILING]


def test_fill_clamps_a_model_timeout_to_the_submit_budget():
    page = _RecordingPage()

    _a_service_with(page).fill("hello", selector="#name", timeout=600_000)

    assert page.fill_timeouts == [CEILING]


def test_select_clamps_a_model_timeout_to_the_submit_budget():
    page = _RecordingPage()

    _a_service_with(page).select("pro", selector="#plan", timeout=600_000)

    assert page.select_timeouts == [CEILING]


def test_defaults_are_left_alone():
    page = _RecordingPage()
    service = _a_service_with(page)

    service.navigate("https://example.com")
    service.click(selector="#ok")

    assert page.goto_timeouts == [30_000]
    assert page.click_timeouts == [5_000]


def test_a_timeout_under_the_budget_is_left_alone():
    page = _RecordingPage()

    _a_service_with(page).wait(selector="#ready", timeout=45_000)

    assert page.selector_timeouts == [45_000]


def test_zero_or_negative_maps_to_the_ceiling():
    page = _RecordingPage()
    service = _a_service_with(page)

    service.navigate("https://example.com", timeout=0)
    service.click(selector="#ok", timeout=-1)
    service.wait(selector="#ready", timeout=0)

    assert page.goto_timeouts == [CEILING]
    assert page.click_timeouts == [CEILING]
    assert page.selector_timeouts == [CEILING]


def test_none_or_junk_falls_back_to_the_default():
    page = _RecordingPage()
    service = _a_service_with(page)

    service.navigate("https://example.com", timeout=None)
    service.click(selector="#ok", timeout="soon")
    service.fill("x", selector="#name", timeout="2000")

    assert page.goto_timeouts == [30_000]
    assert page.click_timeouts == [5_000]
    assert page.fill_timeouts == [2_000]


def test_the_ceiling_stays_below_the_submit_budget():
    assert CEILING < browser_service._BROWSER_OP_BUDGET_S * 1000


def test_submit_waits_exactly_the_budget_the_clamp_allows(monkeypatch):
    """The clamp is only honest while _submit() waits for the same budget."""
    seen = {}

    def fake_wait(self, timeout=None):
        seen["timeout"] = timeout
        return False  # the worker is still busy; the caller gives up

    monkeypatch.setattr(threading.Event, "wait", fake_wait)
    service = BrowserService.__new__(BrowserService)
    service._needs_restart = False
    service._alive = True
    service._task_queue = queue.Queue()
    service._start_thread = lambda: None
    service._reset_idle_timer = lambda: None
    service._driver_connection_lost = lambda: False

    with pytest.raises(TimeoutError) as excinfo:
        service._submit(lambda: None)

    assert seen["timeout"] == browser_service._BROWSER_OP_BUDGET_S
    assert f"({browser_service._BROWSER_OP_BUDGET_S}s)" in str(excinfo.value)
