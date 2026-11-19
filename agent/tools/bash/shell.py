"""Execution-host shell detection and PowerShell 7 script launch helpers."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

_probe_lock = threading.Lock()
_probe_cache = None
_probe_at = 0.0


def detect_pwsh():
    """Probe PowerShell 7 (never Windows PowerShell 5.1), with a short cache."""
    global _probe_cache, _probe_at
    with _probe_lock:
        now = time.monotonic()
        if _probe_cache is not None and now - _probe_at < 30:
            return dict(_probe_cache)
        result = {"available": False, "version": None, "path": None}
        candidates = [shutil.which("pwsh")]
        if sys.platform == "win32":
            for key in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
                root = os.environ.get(key)
                if root:
                    candidates.append(os.path.join(root, "PowerShell", "7", "pwsh.exe"))
        for path in dict.fromkeys(p for p in candidates if p):
            if not os.path.isfile(path):
                continue
            try:
                probe = subprocess.run(
                    [path, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                )
                version = probe.stdout.decode("utf-8", errors="replace").strip()
                if probe.returncode == 0 and re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.\-]+)?", version) and int(version.split('.')[0]) >= 7:
                    result = {"available": True, "version": version, "path": path}
                    break
            except (OSError, subprocess.SubprocessError):
                continue
        _probe_cache, _probe_at = result, now
        return dict(result)


def get_shell_status():
    return {"pwsh": detect_pwsh()}


def prepare_pwsh(command):
    """Return argv + owned temp file; never pass PowerShell through cmd.exe."""
    status = detect_pwsh()
    if not status["available"]:
        raise RuntimeError("PowerShell 7 (pwsh) is unavailable on the execution host. Install it or select CMD in command settings.")
    # A file avoids cmd quoting/length limits. BOM makes Unicode source explicit.
    prefix = """$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
if ($PSVersionTable.PSVersion -ge [version]'7.2') { $PSStyle.OutputRendering = 'PlainText' }
$global:LASTEXITCODE = 0
try {
"""
    suffix = """
    $cowCommandSucceeded = $?
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $cowCommandSucceeded) { exit 1 }
    exit 0
} catch {
    [Console]::Error.WriteLine(($_ | Out-String))
    exit 1
}
"""
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", prefix="cow-bash-", encoding="utf-8-sig", delete=False) as script:
            path = script.name
            script.write(prefix + command + "\n" + suffix)
        return [status["path"], "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path], path
    except Exception:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
