"""Every subprocess the service lifecycle commands run has to be bounded.

``cow start/stop/status`` all go through ``cli.commands.process``, whose win32
branches shell out to ``tasklist`` and ``taskkill``. A hung tasklist is a known
Windows failure under a corrupted process table or extreme load (the browser
tool's identical probe was already given a timeout in chrome_launcher), and
here a wedged probe is worse: ``stop`` polls ``_is_pid_alive`` in a loop, so one
hang freezes every lifecycle command, and the self-restart relay's
``import app`` self-check sits between "old process still running" and "new
process started" with no way out.
"""

import ast
import subprocess

from cli.commands import process


def _win32(monkeypatch):
    monkeypatch.setattr(process, "_IS_WIN", True)


def test_win32_probe_passes_a_timeout(monkeypatch):
    _win32(monkeypatch)
    seen = {}

    def fake_check_output(cmd, **kwargs):
        seen.update(kwargs)
        return b"python.exe    1234 Console   1    12,345 K"

    monkeypatch.setattr(process.subprocess, "check_output", fake_check_output)
    assert process._is_pid_alive(1234) is True
    assert "timeout" in seen, "tasklist probe ran without a timeout"


def test_win32_probe_survives_a_hung_tasklist(monkeypatch):
    _win32(monkeypatch)

    def hung(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="tasklist", timeout=kwargs.get("timeout", 5))

    monkeypatch.setattr(process.subprocess, "check_output", hung)
    # Same posture as every other failure of this probe: unanswerable means
    # the caller's own logic (the 3s liveness loop, the pid-file cleanup)
    # decides, instead of the CLI freezing here.
    assert process._is_pid_alive(1234) is False


def test_win32_kill_passes_a_timeout(monkeypatch):
    _win32(monkeypatch)
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(process.subprocess, "run", fake_run)
    process._kill_pid(1234, force=True)
    assert "timeout" in seen, "taskkill ran without a timeout"


def test_win32_kill_survives_a_hung_taskkill(monkeypatch):
    _win32(monkeypatch)

    def hung(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="taskkill", timeout=kwargs.get("timeout", 10))

    monkeypatch.setattr(process.subprocess, "run", hung)
    # The timeout must degrade, not raise out of `stop`: the liveness loop
    # after the kill re-checks the pid and escalates to force.
    process._kill_pid(1234)


def test_relay_self_check_is_bounded():
    """The relay's `import app` self-check is the gate between the old and the
    new process; a hung import must reach the abort path, not sit there."""
    tree = ast.parse(process._RELAY_SCRIPT)
    runs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "run"
    ]
    assert len(runs) == 1, "the relay script's shape changed; revisit this test"
    assert any(kw.arg == "timeout" for kw in runs[0].keywords), \
        "the self-check subprocess.run lost its timeout"


def test_relay_logs_and_aborts_when_the_self_check_times_out(monkeypatch, tmp_path):
    """The relay's stderr is discarded, so a timed-out self-check has to be
    logged by the relay itself, and the old process must not be signalled."""
    log_file = tmp_path / "nohup.out"
    signalled = []

    def hung(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", hung)
    monkeypatch.setattr("os.kill", lambda pid, sig: signalled.append((pid, sig)))
    monkeypatch.setattr("sys.argv", [
        "-c", str(tmp_path), "python", str(tmp_path / "app.py"),
        str(tmp_path / "cow.pid"), str(log_file), "4321",
    ])

    try:
        exec(compile(process._RELAY_SCRIPT, "<relay>", "exec"), {"__name__": "__main__"})
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("the relay went on past a timed-out self-check")

    assert "self-check timed out" in log_file.read_text()
    assert signalled == [], "the old process was signalled after the self-check failed"
