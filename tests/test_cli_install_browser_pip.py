"""Exercise the Playwright pip install on externally managed Python."""

import sys
import sysconfig

import pytest

from cli.commands import install


@pytest.mark.parametrize(
    "platform, managed, in_venv, help_output, plain_result, expected_flags",
    [
        ("darwin", True, False, b"--break-system-packages", 1, [[], ["--break-system-packages"]]),
        ("darwin", True, False, b"", 1, [[], ["--user"]]),
        ("darwin", False, False, b"--break-system-packages", 1, [[], ["--user"]]),
        ("darwin", True, False, b"--break-system-packages", 0, [[]]),
        ("darwin", True, True, b"--break-system-packages", 1, [[], ["--user"]]),
        ("linux", True, False, b"--break-system-packages", 1, [[], ["--user"]]),
    ],
)
def test_pip_install_fallback(
    monkeypatch, tmp_path, platform, managed, in_venv, help_output, plain_result, expected_flags
):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "prefix", "/venv" if in_venv else sys.base_prefix)
    monkeypatch.setattr(sysconfig, "get_path", lambda name: str(tmp_path))
    if managed:
        (tmp_path / "EXTERNALLY-MANAGED").touch()

    package = "playwright==1.52.0"
    base = [sys.executable, "-m", "pip", "install"]
    pip_calls = []

    def pip_install(command):
        pip_calls.append(command)
        if len(pip_calls) == 1:
            return plain_result
        if platform == "darwin" and managed and not in_venv:
            return int("--break-system-packages" not in command)
        return 0

    def pip_help(command, **kwargs):
        assert command == base + ["--help"]
        return help_output

    monkeypatch.setattr(install.subprocess, "call", pip_install)
    monkeypatch.setattr(install.subprocess, "check_output", pip_help)

    result = install._pip_install(package, lambda *_: None)

    assert pip_calls == [
        base + ["--prefer-binary"] + flags + [package] for flags in expected_flags
    ]
    assert result == int(platform == "darwin" and managed and not help_output)
