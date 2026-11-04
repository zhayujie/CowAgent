"""``/skill install`` typed in chat must give up on its own timeout.

The command runs ``install_skill`` on a worker thread so a slow download cannot
block the chat, with ``_INSTALL_TIMEOUT`` as the budget. ``with
ThreadPoolExecutor(...)`` joins the worker on exit, timeout or not, so the
caller only got the "timed out" message once the stalled install had finished
anyway -- the budget protected nothing.

Letting go of the worker means a second request can arrive while the first is
still writing, so a repeat request for the same skill is refused rather than
started twice on the same directory.
"""
import os
import threading

import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    import plugins.cow_cli.cow_cli  # noqa: F401
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

CowCliPlugin = plugins.instance.plugins["COW_CLI"]


def _stalled_install(monkeypatch, calls, release):
    """An ``install_skill`` that blocks until *release*, recording each call."""
    started = threading.Event()

    def _install(name, agent_id=None):
        from cli.commands.skill import InstallResult
        calls.append((name, agent_id))
        started.set()
        assert release.wait(10), "the stalled install was never released"
        return InstallResult(error="late")

    monkeypatch.setattr("cli.commands.skill.install_skill", _install)
    return started


def test_the_timeout_returns_without_waiting_for_the_worker(monkeypatch):
    calls = []
    release = threading.Event()
    started = _stalled_install(monkeypatch, calls, release)
    monkeypatch.setattr(CowCliPlugin, "_INSTALL_TIMEOUT", 0.05)

    returned = threading.Event()

    def install():
        try:
            CowCliPlugin()._cmd_skill("install slow", None)
        finally:
            returned.set()

    worker = threading.Thread(target=install, daemon=True)
    worker.start()
    try:
        assert started.wait(5)
        # A synchronization deadline, not a latency assertion: the command has
        # to come back while the install it gave up on is still running.
        assert returned.wait(5), "the command blocked until the stalled install finished"
    finally:
        release.set()
        worker.join(10)


def test_a_repeat_request_does_not_start_a_second_writer(monkeypatch):
    calls = []
    release = threading.Event()
    started = _stalled_install(monkeypatch, calls, release)
    monkeypatch.setattr(CowCliPlugin, "_INSTALL_TIMEOUT", 0.05)

    first = threading.Thread(
        target=lambda: CowCliPlugin()._cmd_skill("install slow", None), daemon=True
    )
    first.start()
    try:
        assert started.wait(5)
        reply = CowCliPlugin()._cmd_skill("install slow", None)
        # Refused up front instead of queued behind the running install.
        assert len(calls) == 1, "the repeat request started a second install"
        assert "slow" in reply
    finally:
        release.set()
        first.join(10)


def test_a_finished_install_still_reports_its_result(monkeypatch):
    """Control: the normal path is unchanged by dropping the joined scope."""
    from cli.commands.skill import InstallResult

    calls = []

    def _install(name, agent_id=None):
        calls.append((name, agent_id))
        return InstallResult(installed=["alpha"])

    monkeypatch.setattr("cli.commands.skill.install_skill", _install)
    monkeypatch.setattr(
        CowCliPlugin, "_format_install_result", staticmethod(lambda result, agent_id=None: "formatted")
    )

    assert CowCliPlugin()._cmd_skill("install alpha", None) == "formatted"
    assert calls == [("alpha", None)]

