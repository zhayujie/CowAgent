from types import SimpleNamespace

import pytest

from agent.tools.bash.bash import Bash


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("findstr -i -e cow -e agent", "findstr uses /I"),
        ("python task.py 2>/dev/null", "redirect to nul"),
        ("bash script.sh", "do not invoke bash/sh"),
        ("echo 'hello'", "single quotes literally"),
        ("grep needle file.txt", "use search_files"),
        ("echo one; echo two", "chain commands with &&"),
    ],
)
def test_windows_failure_hint_corrects_detected_shell_mismatches(monkeypatch, command, expected):
    monkeypatch.setattr(Bash, "_IS_WIN", True)

    assert expected in Bash._windows_failure_hint(command)


def test_windows_failure_hint_is_absent_for_an_ordinary_failure(monkeypatch):
    monkeypatch.setattr(Bash, "_IS_WIN", True)

    assert Bash._windows_failure_hint("python missing.py") == ""


def test_failed_windows_command_returns_the_corrective_hint(monkeypatch, tmp_path):
    # Patch the class attribute (not the instance): _windows_failure_hint is a
    # classmethod that reads cls._IS_WIN, so an instance-level patch is ignored
    # and the test would only pass on a real Windows host.
    monkeypatch.setattr(Bash, "_IS_WIN", True)
    tool = Bash({"cwd": str(tmp_path)})
    monkeypatch.setattr(
        tool,
        "_run_streaming",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="FINDSTR: Cannot open -e",
        ),
    )

    result = tool.execute(
        {"command": "pip list 2>nul | findstr -i -e cow -e agent"}
    )

    assert result.status == "error"
    assert "FINDSTR: Cannot open -e" in result.result["output"]
    assert "Windows cmd.exe hint" in result.result["output"]
    assert "findstr /I" in result.result["output"]
