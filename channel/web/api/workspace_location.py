"""The settings view's workspace location card: /api/workspace-location.

Shows where the Agent workspace lives and schedules a move to another folder.
The move itself runs on the next start (common/workspace_migration.py), so this
also restarts the service where it can, the same way the one-click update does.
"""

import _thread
import json
import os
import shutil
import subprocess
import sys
import threading
from typing import List, Optional, Tuple

import web

from channel.web.core._common import (
    _can_reveal_in_file_manager,
    _is_loopback_request,
    _is_password_enabled,
    _require_auth,
)
from common import workspace_migration as wm
from common.log import logger

_PICK_TIMEOUT = 600
_pick_lock = threading.Lock()

# Run in a child process: Tk wants the main thread, and the server has none to spare.
_TK_PICK_SCRIPT = r"""
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
path = filedialog.askdirectory(parent=root, title=sys.argv[1], initialdir=sys.argv[2] or None, mustexist=True)
root.destroy()
sys.stdout.buffer.write((path or "").encode("utf-8"))
"""

_PS_PICK_SCRIPT = (
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
    "$d.Description = $env:COW_PICK_TITLE; $d.ShowNewFolderButton = $true;"
    "$d.SelectedPath = $env:COW_PICK_START;"
    "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true};"
    "if ($d.ShowDialog($owner) -eq 'OK') {"
    " $b = [Text.Encoding]::UTF8.GetBytes($d.SelectedPath);"
    " [Console]::OpenStandardOutput().Write($b, 0, $b.Length) }"
)


def _pick_commands(title: str, start: str) -> List[Tuple[List[str], Tuple[int, ...]]]:
    """Native folder dialogs to try, each with the exit codes that mean "cancelled"."""
    tk = ([sys.executable, "-c", _TK_PICK_SCRIPT, title, start], ())
    if sys.platform == "darwin":
        script = ['-e', 'on run argv', '-e', 'activate',
                  '-e', 'POSIX path of (choose folder with prompt (item 1 of argv))', '-e', 'end run']
        return [(["osascript", *script, title], ())]
    if sys.platform == "win32":
        ps = (["powershell", "-NoProfile", "-STA", "-Command", _PS_PICK_SCRIPT], ())
        return [tk, ps]
    cmds = []
    if shutil.which("zenity"):
        cmds.append((["zenity", "--file-selection", "--directory", f"--title={title}",
                      f"--filename={start.rstrip('/')}/"], (1,)))
    if shutil.which("kdialog"):
        cmds.append((["kdialog", "--getexistingdirectory", start or "~", "--title", title], (1,)))
    cmds.append(tk)
    return cmds


def _native_pick_folder(title: str, start: str) -> Optional[str]:
    """Show the OS folder dialog on this machine. Returns the chosen path, ""
    when the user cancelled, or None when no dialog could be shown."""
    env = {**os.environ, "COW_PICK_TITLE": title, "COW_PICK_START": start}
    for cmd, cancel_codes in _pick_commands(title, start):
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=_PICK_TIMEOUT, env=env,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return ""
        except OSError:
            continue
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode == 0:
            return os.path.normpath(out) if out else ""
        # osascript reports a cancelled dialog as error -128.
        if proc.returncode in cancel_codes or b"-128" in proc.stderr:
            return ""
        logger.debug(f"[WebChannel] folder dialog {cmd[0]} failed: {proc.stderr[-300:]!r}")
    return None


def _unsupported_reason() -> str:
    if os.environ.get("COW_DESKTOP") == "1":
        # The desktop client has its own card for this, in its shell.
        return "desktop"
    from cli.update_service import _is_docker_install

    if _is_docker_install():
        return "docker"
    if wm.managed_by_env():
        return "managed_by_env"
    if not wm.links_supported():
        return "python_too_old"
    # Without a password anyone who reaches the port is "logged in"; only let
    # the person sitting at the machine point the Agent at another folder.
    if not _is_password_enabled() and not _is_loopback_request():
        return "remote_without_password"
    return ""


def _restart_mode() -> str:
    """'auto' where the service can restart itself, else 'manual'."""
    # The terminal channel reads stdin, which a restarted (or detached) process
    # would have to share with the shell.
    return "manual" if "--cmd" in sys.argv else "auto"


# `cow self-restart` is POSIX-only. This relay waits for the old process to
# exit, then starts app.py again where it ran: in the same console window when
# there is one (Ctrl+C there still stops it), else hidden and logging to the
# CLI's log file the way `cow start` runs it.
_WIN_RELAY_SCRIPT = r"""
import subprocess, sys, time, _winapi

python, app_py, root, old_pid, log_file, pid_file = sys.argv[1:7]
args = sys.argv[7:]


def gone(pid, seconds):
    try:
        handle = _winapi.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    except OSError:
        return True
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if _winapi.WaitForSingleObject(handle, 200) == 0:
                return True
        return False
    finally:
        _winapi.CloseHandle(handle)


try:
    if not gone(int(old_pid), 20):
        subprocess.call(["taskkill", "/F", "/PID", old_pid],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        gone(int(old_pid), 10)
except KeyboardInterrupt:
    sys.exit(130)

if not log_file:
    child = subprocess.Popen([python, app_py] + args, cwd=root)
    while True:
        try:
            sys.exit(child.wait())
        except KeyboardInterrupt:
            pass

with open(log_file, "a") as log:
    child = subprocess.Popen(
        [python, app_py] + args, cwd=root,
        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000,  # CREATE_NO_WINDOW
    )
with open(pid_file, "w") as f:
    f.write(str(child.pid))
"""


def _restart_service_windows() -> None:
    from cli.commands.process import _get_log_file, _get_pid_file
    from cli.utils import get_project_root

    root = get_project_root()
    in_console = bool(sys.stdout and sys.stdout.isatty())
    kwargs = {"cwd": root}
    if not in_console:
        kwargs.update(
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000,  # CREATE_NO_WINDOW
        )
    subprocess.Popen(
        [
            sys.executable, "-c", _WIN_RELAY_SCRIPT,
            sys.executable, os.path.join(root, "app.py"), root, str(os.getpid()),
            "" if in_console else _get_log_file(), _get_pid_file(),
            *sys.argv[1:],
        ],
        **kwargs,
    )
    # Leave the way Ctrl+C does (user data saved), once this reply is out.
    threading.Timer(0.5, _thread.interrupt_main).start()


def _restart_service() -> None:
    """Hand the restart to the detached relay behind `cow self-restart`."""
    if sys.platform == "win32":
        _restart_service_windows()
        return
    from cli.commands.process import _RELAY_SCRIPT, _get_log_file, _get_pid_file
    from cli.utils import get_project_root

    root = get_project_root()
    subprocess.Popen(
        [
            sys.executable, "-c", _RELAY_SCRIPT,
            root, sys.executable, os.path.join(root, "app.py"),
            _get_pid_file(), _get_log_file(), str(os.getpid()),
        ],
        cwd=root,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _info() -> dict:
    reason = _unsupported_reason()
    return {
        "status": "success",
        "supported": not reason,
        "unsupported_reason": reason,
        "workspace": wm.real_workspace(),
        "pending": wm.read_pending(),
        "result": wm.read_result(),
        "restart": _restart_mode(),
        # A native dialog only helps when it opens in front of the person asking.
        "native_picker": _can_reveal_in_file_manager(),
    }


class WorkspaceLocationHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if web.input(usage='').usage:
                return json.dumps({"status": "success", "bytes": wm.workspace_size()})
            return json.dumps(_info(), ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Workspace location error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            data = json.loads(web.data() or b"{}")
            action = data.get("action")
            if action == "dismiss":
                wm.dismiss_result()
                return json.dumps({"status": "success"})

            reason = _unsupported_reason()
            if reason:
                return json.dumps({"status": "error", "code": reason})

            if action == "pick":
                if not _can_reveal_in_file_manager():
                    return json.dumps({"status": "error", "code": "pick_unsupported"})
                if not _pick_lock.acquire(blocking=False):
                    return json.dumps({"status": "error", "code": "pick_busy"})
                try:
                    start = os.path.dirname(wm.real_workspace())
                    path = _native_pick_folder(str(data.get("title") or ""), start)
                finally:
                    _pick_lock.release()
                if path is None:
                    return json.dumps({"status": "error", "code": "pick_unsupported"})
                return json.dumps({"status": "success", "path": path}, ensure_ascii=False)
            if action == "check":
                result = wm.check_target(data.get("parent", ""))
                return json.dumps({"status": "success", "check": result}, ensure_ascii=False)
            if action == "schedule":
                result = wm.schedule(data.get("parent", ""), bool(data.get("keep_link", True)))
                if not result.get("ok"):
                    return json.dumps({"status": "error", "code": result.get("code"),
                                       "detail": result.get("detail", "")}, ensure_ascii=False)
                return json.dumps({**_info(), "check": result}, ensure_ascii=False)
            if action == "cancel":
                wm.cancel()
                return json.dumps(_info(), ensure_ascii=False)
            if action == "restart":
                if not wm.read_pending():
                    return json.dumps({"status": "error", "code": "nothing_pending"})
                if _restart_mode() != "auto":
                    return json.dumps({"status": "error", "code": "restart_unsupported"})
                logger.info("[WebChannel] restarting to move the workspace")
                _restart_service()
                return json.dumps({"status": "success"})
            return json.dumps({"status": "error", "message": f"unknown action: {action}"})
        except Exception as e:
            logger.error(f"[WebChannel] Workspace location error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
