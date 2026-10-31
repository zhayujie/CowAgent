# encoding:utf-8
"""The browser navigate action must re-validate the URL the browser landed on.

``page.goto`` follows redirects on its own, so a model-supplied public URL
can bounce the browser into a link-local / cloud-metadata address. The entry
URL is validated -- ``url_safety`` spells out the contract: "validating only
the original URL leaves the redirect hop unguarded" -- but the final one was
not, and the auto-snapshot handed that page's content straight to the model.
"""

from agent.tools.browser.browser_tool import BrowserTool

PUBLIC = "http://93.184.216.34/"  # a public literal: no DNS needed either side
METADATA = "http://169.254.169.254/latest/meta-data/"
SECRET = "ami-id: ami-0abcdef1234567890\nrole: prod"


class _Service:
    """Stands in for BrowserService: reports a final URL, snapshots on demand."""

    def __init__(self, final_url, snapshot=SECRET):
        self._final_url = final_url
        self._snapshot = snapshot
        self.snapshot_called = False

    def navigate(self, url, timeout=None):
        return {"url": self._final_url, "title": "t", "status": 200}

    def snapshot(self):
        self.snapshot_called = True
        return self._snapshot


def _tool(monkeypatch, service):
    tool = BrowserTool()
    monkeypatch.setattr(tool, "_get_service", lambda: service)
    return tool


def test_navigate_rechecks_the_url_the_browser_landed_on(monkeypatch):
    service = _Service(METADATA)
    tool = _tool(monkeypatch, service)

    result = tool._do_navigate({"url": PUBLIC})

    assert result.status == "error"
    assert "169.254" in str(result.result)
    # The snapshot of the redirected page must not reach the model.
    assert not service.snapshot_called
    assert SECRET not in str(result.result)


def test_navigate_without_a_redirect_still_snapshots(monkeypatch):
    service = _Service(PUBLIC)
    tool = _tool(monkeypatch, service)

    result = tool._do_navigate({"url": PUBLIC})

    assert result.status == "success"
    assert service.snapshot_called
    assert SECRET in result.result


def test_navigate_recheck_is_skipped_when_private_targets_are_allowed(monkeypatch):
    service = _Service(METADATA)
    tool = _tool(monkeypatch, service)
    monkeypatch.setattr(tool, "_allow_private_targets", lambda: True)

    result = tool._do_navigate({"url": PUBLIC})

    assert result.status == "success"
    assert service.snapshot_called
