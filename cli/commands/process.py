"""cow start/stop/restart/status/logs - Process management commands."""

import os
import sys
import subprocess
import time
from typing import Optional

import click

from cli.utils import get_project_root

_IS_WIN = sys.platform == "win32"


def _get_pid_file():
    return os.path.join(get_project_root(), ".cow.pid")


def _get_log_file():
    return os.path.join(get_project_root(), "nohup.out")


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process is still running (cross-platform)."""
    if _IS_WIN:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                stderr=subprocess.DEVNULL,
            )
            return str(pid) in out.decode(errors="ignore")
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def _kill_pid(pid: int, force: bool = False):
    """Terminate a process by PID (cross-platform)."""
    if _IS_WIN:
        flag = "/F" if force else ""
        cmd = ["taskkill"]
        if force:
            cmd.append("/F")
        cmd.extend(["/PID", str(pid)])
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        import signal
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)


def _read_pid() -> Optional[int]:
    pid_file = _get_pid_file()
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
        if _is_pid_alive(pid):
            return pid
        os.remove(pid_file)
        return None
    except (ValueError, OSError):
        try:
            os.remove(pid_file)
        except OSError:
            pass
        return None


def _write_pid(pid: int):
    with open(_get_pid_file(), "w") as f:
        f.write(str(pid))


def _remove_pid():
    pid_file = _get_pid_file()
    if os.path.exists(pid_file):
        os.remove(pid_file)


@click.command()
@click.option("--foreground", "-f", is_flag=True, help="Run in foreground (don't daemonize)")
@click.option("--no-logs", is_flag=True, help="Don't tail logs after starting")
def start(foreground, no_logs):
    """Start CowAgent."""
    pid = _read_pid()
    if pid:
        click.echo(f"CowAgent is already running (PID: {pid}).")
        return

    root = get_project_root()
    app_py = os.path.join(root, "app.py")
    if not os.path.exists(app_py):
        click.echo("Error: app.py not found in project root.", err=True)
        sys.exit(1)

    python = sys.executable

    if foreground:
        click.echo("Starting CowAgent in foreground...")
        if _IS_WIN:
            sys.exit(subprocess.call([python, app_py], cwd=root))
        else:
            os.execv(python, [python, app_py])
    else:
        log_file = _get_log_file()
        click.echo("Starting CowAgent...")

        popen_kwargs = dict(cwd=root)
        if _IS_WIN:
            CREATE_NO_WINDOW = 0x08000000
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True

        with open(log_file, "a") as log:
            proc = subprocess.Popen(
                [python, app_py],
                stdout=log,
                stderr=log,
                **popen_kwargs,
            )
        _write_pid(proc.pid)
        click.echo(click.style(f"✓ CowAgent started (PID: {proc.pid})", fg="green"))
        click.echo(f"  Logs: {log_file}")

        if not no_logs:
            click.echo("  Press Ctrl+C to stop tailing logs.\n")
            _tail_log(log_file)


@click.command()
def stop():
    """Stop CowAgent."""
    pid = _read_pid()
    if not pid:
        click.echo("CowAgent is not running.")
        return

    click.echo(f"Stopping CowAgent (PID: {pid})...")
    try:
        _kill_pid(pid)
        for _ in range(30):
            time.sleep(0.1)
            if not _is_pid_alive(pid):
                break
        else:
            _kill_pid(pid, force=True)
    except (ProcessLookupError, OSError):
        pass

    _remove_pid()
    click.echo(click.style("✓ CowAgent stopped.", fg="green"))


@click.command()
@click.option("--no-logs", is_flag=True, help="Don't tail logs after restarting")
@click.pass_context
def restart(ctx, no_logs):
    """Restart CowAgent."""
    ctx.invoke(stop)
    time.sleep(1)
    ctx.invoke(start, no_logs=no_logs)


@click.command()
@click.pass_context
def update(ctx):
    """Update CowAgent and restart."""
    root = get_project_root()

    # 1. Stop service first so git pull won't conflict with running code
    ctx.invoke(stop)

    # 2. Git pull
    if os.path.isdir(os.path.join(root, ".git")):
        click.echo("Pulling latest code...")
        ret = subprocess.call(["git", "pull"], cwd=root)
        if ret != 0:
            click.echo("Error: git pull failed.", err=True)
            sys.exit(1)
    else:
        click.echo("Not a git repository, skipping code update.")

    python = sys.executable
    req_file = os.path.join(root, "requirements.txt")

    if _IS_WIN:
        # On Windows, `cow.exe` (this process) locks the exe file, so
        # `pip install -e .` fails with WinError 5.  Write a small .bat
        # helper that waits for cow.exe to exit, then installs & starts.
        bat = os.path.join(root, "_cow_update.bat")
        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "echo Waiting for cow.exe to exit...",
            "timeout /t 3 /nobreak >nul",
        ]
        if os.path.exists(req_file):
            lines.append(f'echo Installing dependencies...')
            lines.append(f'"{python}" -m pip install -r requirements.txt -q')
        lines += [
            "echo Reinstalling cow CLI...",
            f'"{python}" -m pip install -e . -q',
            "echo Starting CowAgent...",
            f'"{python}" -m cli.cli start --no-logs',
            "echo.",
            "echo Update complete. You can close this window.",
            "pause >nul",
            "del \"%~f0\"",
        ]
        with open(bat, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        subprocess.Popen(
            ["cmd.exe", "/c", "start", "CowAgent Update", "/wait", bat],
            cwd=root,
        )
        click.echo(click.style(
            "✓ Update script launched. Please follow the new window for progress.",
            fg="green"))
    else:
        # 3. Install dependencies
        if os.path.exists(req_file):
            click.echo("Installing dependencies...")
            subprocess.call(
                [python, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
                cwd=root,
            )
        click.echo("Reinstalling cow CLI...")
        subprocess.call(
            [python, "-m", "pip", "install", "-e", ".", "-q"],
            cwd=root,
        )

        # 4. Start service
        click.echo("")
        time.sleep(1)
        ctx.invoke(start, no_logs=False)


@click.command()
def status():
    """Show CowAgent running status."""
    from cli import __version__
    from cli.utils import load_config_json

    pid = _read_pid()
    if pid:
        click.echo(click.style(f"● CowAgent is running (PID: {pid})", fg="green"))
    else:
        click.echo(click.style("● CowAgent is not running", fg="red"))

    click.echo(f"  版本: v{__version__}")

    cfg = load_config_json()
    if cfg:
        channel = cfg.get("channel_type", "unknown")
        if isinstance(channel, list):
            channel = ", ".join(channel)
        click.echo(f"  通道: {channel}")
        click.echo(f"  模型: {cfg.get('model', 'unknown')}")
        mode = "Chat" if cfg.get("agent") is False else "Agent"
        click.echo(f"  模式: {mode}")


@click.command()
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def logs(follow, lines):
    """View CowAgent logs."""
    log_file = _get_log_file()
    if not os.path.exists(log_file):
        click.echo("No log file found.")
        return

    if follow:
        _tail_log(log_file, lines)
    else:
        _print_last_lines(log_file, lines)


def _print_last_lines(file_path: str, n: int = 50):
    """Print the last N lines of a file (cross-platform)."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        for line in all_lines[-n:]:
            click.echo(line, nl=False)
    except Exception as e:
        click.echo(f"Error reading log file: {e}", err=True)


def _tail_log(log_file: str, lines: int = 50):
    """Follow log file output. Blocks until Ctrl+C (cross-platform)."""
    _print_last_lines(log_file, lines)

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    click.echo(line, nl=False)
                else:
                    time.sleep(0.3)
    except KeyboardInterrupt:
        pass
