# encoding:utf-8
"""`cow install-browser` must install playwright into an externally managed Python.

Homebrew Python 3.11+ carries a PEP 668 marker, so pip rejects both the plain
and the --user install. run.sh already installs CowAgent's own requirements
there with --break-system-packages; the installer has to do the same, but only
when pip knows the flag.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.commands import install


def _fake_pip(monkeypatch, results, supports_flag):
    calls = []

    def call(cmd, **kw):
        calls.append(cmd)
        return results.pop(0)

    monkeypatch.setattr(install.subprocess, "call", call)
    monkeypatch.setattr(install, "_pip_supports_break_system_packages", lambda python: supports_flag)
    return calls


def _flags(calls):
    return [[a for a in cmd if a in ("--break-system-packages", "--user")] for cmd in calls]


def test_plain_install_success_needs_no_retry(monkeypatch):
    calls = _fake_pip(monkeypatch, [0], supports_flag=True)

    assert install._pip_install("playwright==1.52.0", lambda *a: None) == 0
    assert _flags(calls) == [[]]


def test_externally_managed_retries_with_break_system_packages(monkeypatch):
    calls = _fake_pip(monkeypatch, [1, 0], supports_flag=True)

    assert install._pip_install("playwright==1.52.0", lambda *a: None) == 0
    assert _flags(calls) == [[], ["--break-system-packages"]]
    assert calls[1][-1] == "playwright==1.52.0"


def test_old_pip_without_the_flag_falls_back_to_user(monkeypatch):
    calls = _fake_pip(monkeypatch, [1, 0], supports_flag=False)

    assert install._pip_install("playwright==1.52.0", lambda *a: None) == 0
    assert _flags(calls) == [[], ["--user"]]


def test_user_is_the_last_resort(monkeypatch):
    calls = _fake_pip(monkeypatch, [1, 1, 1], supports_flag=True)

    assert install._pip_install("playwright==1.52.0", lambda *a: None) == 1
    assert _flags(calls) == [[], ["--break-system-packages"], ["--user"]]


def test_flag_probe_reads_pip_help(monkeypatch):
    class _Done:
        def __init__(self, out):
            self.stdout = out

    help_text = b"  --break-system-packages  Allow pip to modify"
    monkeypatch.setattr(install.subprocess, "run", lambda *a, **kw: _Done(help_text))
    assert install._pip_supports_break_system_packages(sys.executable) is True

    monkeypatch.setattr(install.subprocess, "run", lambda *a, **kw: _Done(b"  --user  Install to the user site"))
    assert install._pip_supports_break_system_packages(sys.executable) is False

    def boom(*a, **kw):
        raise OSError("no pip")

    monkeypatch.setattr(install.subprocess, "run", boom)
    assert install._pip_supports_break_system_packages(sys.executable) is False
