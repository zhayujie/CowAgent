import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.tools.bash.bash import Bash
from agent.tools.read.read import Read


posix_only = pytest.mark.skipif(Bash._IS_WIN, reason="POSIX shell command")
windows_only = pytest.mark.skipif(not Bash._IS_WIN, reason="Windows integration test")


def _windows_pid_command(pid_file):
    path = str(pid_file).replace("\\", "\\\\")
    return (
        f'"{sys.executable}" -c '
        f'"import os,time;open(r\'{path}\',\'w\').write(str(os.getpid()));time.sleep(30)"'
    )


def _windows_pid_is_running(pid):
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    return f'"{pid}"' in result.stdout


def _windows_kill_pid_file(pid_file):
    if pid_file.exists():
        subprocess.run(
            ["taskkill", "/F", "/PID", pid_file.read_text()],
            capture_output=True,
        )


@posix_only
def test_fast_command_returns_output_without_progress(tmp_path):
    tool = Bash({"cwd": str(tmp_path)})
    progress = []
    tool.progress_callback = progress.append

    result = tool.execute({"command": "printf fast"})

    assert result.status == "success"
    assert result.result["output"] == "fast"
    assert progress == []


@posix_only
def test_timeout_returns_promptly(tmp_path):
    tool = Bash({"cwd": str(tmp_path)})
    started = time.monotonic()

    result = tool.execute({"command": "sleep 10", "timeout": 1})

    assert result.status == "error"
    assert "timed out after 1 seconds" in result.result
    assert time.monotonic() - started < 3


@posix_only
def test_cancel_stops_a_running_command(tmp_path):
    """A user cancel must not wait out the remaining timeout."""
    tool = Bash({"cwd": str(tmp_path)})
    tool.cancel_event = threading.Event()
    threading.Timer(0.5, tool.cancel_event.set).start()
    started = time.monotonic()

    result = tool.execute({"command": "sleep 30", "timeout": 60})

    assert result.status == "error"
    assert "cancelled" in result.result
    assert time.monotonic() - started < 5


@posix_only
def test_background_process_holding_pipe_does_not_hang(tmp_path):
    tool = Bash({"cwd": str(tmp_path)})
    started = time.monotonic()

    result = tool.execute({"command": "sleep 10 & printf done", "timeout": 3})

    assert result.status == "success"
    assert result.result["output"] == "done"
    assert time.monotonic() - started < 7


@posix_only
def test_output_without_trailing_newline_streams_progress(tmp_path):
    tool = Bash({"cwd": str(tmp_path)})
    progress = []
    tool.progress_callback = progress.append

    result = tool.execute({
        "command": "for i in 1 2 3 4 5; do printf .; sleep 0.3; done",
        "timeout": 5,
    })

    assert result.status == "success"
    assert result.result["output"] == "....."
    assert progress
    assert progress[-1].endswith(".")


def test_windows_kill_uses_taskkill_for_process_tree():
    tool = Bash()
    process = type("Process", (), {"pid": 1234, "poll": lambda self: None, "kill": lambda self: None})()

    with patch.object(tool, "_IS_WIN", True), patch.object(subprocess, "run") as run:
        run.return_value.returncode = 0
        tool._kill_process(process)

    run.assert_called_once_with(
        ["taskkill", "/F", "/T", "/PID", "1234"],
        capture_output=True,
        timeout=5,
    )


def test_windows_kill_falls_back_when_taskkill_fails():
    tool = Bash()
    process = type("Process", (), {"pid": 1234, "poll": lambda self: None, "kill": lambda self: None})()

    with patch.object(tool, "_IS_WIN", True), \
            patch.object(subprocess, "run", side_effect=OSError), \
            patch.object(process, "kill") as kill:
        tool._kill_process(process)

    kill.assert_called_once()


def test_windows_chcp_prefix_uses_unconditional_separator_so_chcp_failure_does_not_abort_command(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Bash, "_IS_WIN", True)
    tool = Bash({"cwd": str(tmp_path)})
    captured = {}

    def fake_run_streaming(command, timeout, env, dotenv_vars):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr(tool, "_run_streaming", fake_run_streaming)

    result = tool.execute({"command": "echo hello"})

    assert result.status == "success"
    assert captured["command"] == "chcp 65001 >nul 2>&1 & echo hello"


def test_windows_chcp_prefix_does_not_break_soft_exit_code_1_interpretation(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Bash, "_IS_WIN", True)
    tool = Bash({"cwd": str(tmp_path)})

    monkeypatch.setattr(
        tool,
        "_run_streaming",
        lambda command, timeout, env, dotenv_vars: SimpleNamespace(
            returncode=1, stdout="", stderr=""
        ),
    )

    result = tool.execute({"command": "diff a.txt b.txt"})

    assert result.status == "success"
    assert "[Exit code 1: Files differ]" in result.result["output"]


def test_windows_multiline_python_c_is_moved_into_a_temp_file(monkeypatch, tmp_path):
    monkeypatch.setattr(Bash, "_IS_WIN", True)
    tool = Bash({"cwd": str(tmp_path)})
    captured = {}

    def fake_run_streaming(command, timeout, env, dotenv_vars):
        captured["command"] = command
        path = bytes.fromhex(re.search(r"fromhex\('([0-9a-f]+)'\)", command).group(1)).decode("utf-8")
        with open(path, encoding="utf-8") as f:
            captured["code"] = f.read()
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(tool, "_run_streaming", fake_run_streaming)

    result = tool.execute({"command": 'python -c "import os\nprint(\'ok\')" && echo "done"'})

    assert result.status == "success"
    assert "\n" not in captured["command"]
    assert captured["command"].startswith('chcp 65001 >nul 2>&1 & python -c "exec(compile(')
    assert captured["command"].endswith('&& echo "done"')
    assert captured["code"] == "import os\nprint('ok')"


def test_rewritten_python_c_keeps_cwd_on_sys_path(tmp_path):
    (tmp_path / "local_mod.py").write_text("VALUE = 'from-cwd'\n", encoding="utf-8")
    command = f'"{sys.executable}" -c "import local_mod\nprint(local_mod.VALUE)"'

    rewritten, path = Bash._rewrite_python_c(command)
    try:
        assert path and "\n" not in rewritten
        result = subprocess.run(rewritten, shell=True, cwd=tmp_path, capture_output=True, text=True)
    finally:
        os.remove(path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "from-cwd"


def test_python_c_rewrite_ignores_script_arguments_named_c():
    command = 'python tool.py -c "a\nb"'

    assert Bash._rewrite_python_c(command) == (command, None)


@windows_only
def test_windows_timeout_kills_process_tree(tmp_path):
    pid_file = tmp_path / "timeout-child.pid"
    child_command = _windows_pid_command(pid_file)
    tool = Bash({"cwd": str(tmp_path)})
    started = time.monotonic()

    try:
        result = tool.execute({
            "command": f'start "" /b {child_command} & ping -n 30 127.0.0.1 >nul',
            "timeout": 1,
        })

        assert result.status == "error"
        assert "timed out after 1 seconds" in result.result
        assert time.monotonic() - started < 8
        assert pid_file.exists()
        time.sleep(0.5)
        assert not _windows_pid_is_running(pid_file.read_text())
    finally:
        _windows_kill_pid_file(pid_file)


@windows_only
def test_windows_long_running_command_streams_progress(tmp_path):
    tool = Bash({"cwd": str(tmp_path)})
    progress = []
    tool.progress_callback = progress.append

    result = tool.execute({
        "command": (
            f'"{sys.executable}" -u -c '
            '"import sys,time; '
            "[(sys.stdout.write('.'),sys.stdout.flush(),time.sleep(0.3)) "
            'for _ in range(5)]"'
        ),
        "timeout": 5,
    })

    assert result.status == "success"
    assert result.result["output"] == "....."
    assert progress
    assert progress[-1].endswith(".")


@windows_only
def test_windows_background_process_holding_pipe_does_not_hang(tmp_path):
    pid_file = tmp_path / "background-child.pid"
    child_command = _windows_pid_command(pid_file)
    tool = Bash({"cwd": str(tmp_path)})
    started = time.monotonic()

    try:
        result = tool.execute({
            "command": f'start "" /b {child_command} & echo done',
            "timeout": 3,
        })

        assert result.status == "success"
        assert result.result["output"].strip() == "done"
        assert time.monotonic() - started < 8
        assert pid_file.exists()
    finally:
        _windows_kill_pid_file(pid_file)


@windows_only
def test_windows_full_output_log_keeps_the_commands_line_breaks(tmp_path, monkeypatch):
    # cmd ends every line with CRLF. Saved in text mode, each one became
    # CR CR LF, so the read tool showed a blank line after every line and the
    # line numbers in the truncation notice pointed at the wrong part of the log.
    original = tempfile.NamedTemporaryFile

    def log_in_tmp_path(*args, **kwargs):
        kwargs["dir"] = str(tmp_path)
        return original(*args, **kwargs)

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", log_in_tmp_path)
    tool = Bash({"cwd": str(tmp_path)})

    result = tool.execute({"command": "for /L %i in (1,1,2100) do @echo row %i", "timeout": 60})

    assert result.status == "success", result.result
    path = result.result["details"]["full_output_path"]
    assert Path(path).read_bytes() == b"".join(b"row %d\r\n" % i for i in range(1, 2101))
    start = int(re.search(r"\[Showing lines (\d+)-", result.result["output"]).group(1))
    page = Read({"cwd": str(tmp_path)}).execute({"path": path, "offset": start, "limit": 1}).result
    assert page["content"].startswith(f"{start}|row {start}\n")
    assert page["total_lines"] == 2100
