"""What the preview server adds to a generated HTML page before serving it."""

from channel.web.api.files import _inject_preview_chrome


def _guard_at(out: bytes) -> int:
    return out.index(b"E.scrollIntoView=")


def test_guard_runs_before_the_pages_own_scripts():
    page = b"<!doctype html><html><head><title>t</title><script>go()</script></head><body></body></html>"
    out = _inject_preview_chrome(page)
    assert _guard_at(out) < out.index(b"<title>")
    assert _guard_at(out) < out.index(b"go()")


def test_page_without_head_still_gets_the_guard_first():
    out = _inject_preview_chrome(b"<html><body><script>go()</script></body></html>")
    assert out.startswith(b"<html>")
    assert _guard_at(out) < out.index(b"go()")


def test_fragment_gets_the_guard_prepended():
    out = _inject_preview_chrome(b"<script>go()</script>")
    assert _guard_at(out) < out.index(b"go()")


def test_guard_is_injected_once():
    out = _inject_preview_chrome(b"<html><head></head><body><head></head></body></html>")
    assert out.count(b"E.scrollIntoView=") == 1


def test_storage_stand_ins_come_before_everything_else():
    # The sandbox makes reading localStorage throw; a page that reads a saved
    # theme first would otherwise stop before showing its content.
    page = b"<!doctype html><html><head><script>localStorage.getItem('theme')</script></head></html>"
    out = _inject_preview_chrome(page)
    shim = out.index(b"['localStorage','sessionStorage']")
    assert shim < _guard_at(out)
    assert shim < out.index(b"localStorage.getItem('theme')")
    assert out.count(b"['localStorage','sessionStorage']") == 1
