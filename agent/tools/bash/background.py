"""
Registry for shell commands running in the background.

Without this the model hand-rolls backgrounding - `nohup cmd &`, echo the PID,
`sleep 1`, then curl to see whether it came up - which is both verbose and
unreliable (the sleep is always either too short or wasted). Here the tool
starts the process, hands back an id, and later calls read whatever the process
has printed since the last look.

Tool instances are created per call, so the registry has to live at module
level to outlive them.

Living at module level also means every conversation in the process shares it,
so each job records the identity that started it and every lookup is answered
for that identity only. Otherwise one conversation reads or kills another's
server, and its own finished jobs are the ones the cap evicts.

Processes are deliberately NOT killed when the agent finishes: a background
command is usually a server the user asked to have running. Use kill() to stop
one on purpose.
"""

import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

from agent.tools.bash.decode import decode_output

_IS_WIN = sys.platform == "win32"

# Per-job output cap. A chatty server would otherwise grow without bound; the
# oldest output is dropped first since the tail is what matters when checking
# on a process.
_MAX_BUFFER_BYTES = 256 * 1024

# Finished jobs stay readable for a while so a late poll still sees the exit
# code, but the registry must not grow forever. The cap is per conversation:
# a busy conversation then evicts its own history instead of another's.
_MAX_JOBS = 20


def _owner_key() -> Tuple[str, str, str]:
    """The conversation a job belongs to.

    The ambient identity names the Agent, the end user and the session, which is
    exactly what a job is shared with; ``run_id`` is left out on purpose, since a
    job started in one task has to stay readable on the next turn of the same
    conversation.
    """
    from common.runtime_identity import current_identity

    identity = current_identity()
    return (identity.agent_id or "", identity.user_id or "", identity.session_id or "")


class _Job:
    def __init__(self, job_id: str, command: str, process: subprocess.Popen,
                 temp_script: Optional[str] = None,
                 owner: Tuple[str, str, str] = ("", "", "")):
        self.id = job_id
        self.command = command
        self.process = process
        self.temp_script = temp_script
        self.owner = owner
        self.started_at = time.time()
        self.buffer = bytearray()
        self.cursor = 0
        self.dropped = 0
        self.lock = threading.Lock()
        self.readers: List[threading.Thread] = []

    def append(self, chunk: bytes) -> None:
        with self.lock:
            self.buffer.extend(chunk)
            overflow = len(self.buffer) - _MAX_BUFFER_BYTES
            if overflow > 0:
                del self.buffer[:overflow]
                self.cursor = max(0, self.cursor - overflow)
                self.dropped += overflow

    def take_new_output(self, final: bool = False) -> Tuple[str, int]:
        """Return output printed since the last call, and bytes lost to the cap."""
        with self.lock:
            chunk = bytes(self.buffer[self.cursor:])
            if not final:
                # A pipe read or UI poll can bisect a UTF-8 character. Retain
                # only an incomplete trailing sequence for the next poll.
                start = len(chunk) - 1
                while start >= 0 and len(chunk) - start <= 4 and chunk[start] & 0xC0 == 0x80:
                    start -= 1
                if start >= 0 and chunk[start] >= 0xC2:
                    try:
                        chunk[start:].decode("utf-8")
                    except UnicodeDecodeError as exc:
                        if exc.reason == "unexpected end of data":
                            chunk = chunk[:start]
            self.cursor += len(chunk)
            dropped, self.dropped = self.dropped, 0
        return decode_output(chunk), dropped

    @property
    def running(self) -> bool:
        return self.process.poll() is None


_lock = threading.Lock()
_jobs: Dict[str, _Job] = {}


def _drain(job: _Job, stream) -> None:
    try:
        while True:
            chunk = os.read(stream.fileno(), 4096)
            if not chunk:
                break
            job.append(chunk)
    except (OSError, ValueError):
        pass


def _evict_finished(owner: Tuple[str, str, str]) -> None:
    """Drop the oldest finished jobs of *owner* once its share is full."""
    mine = [j for j in _jobs.values() if j.owner == owner]
    if len(mine) < _MAX_JOBS:
        return
    finished = sorted(
        (j for j in mine if not j.running),
        key=lambda j: j.started_at,
    )
    for job in finished[: len(mine) - _MAX_JOBS + 1]:
        _cleanup(job)
        _jobs.pop(job.id, None)


def _cleanup(job: _Job) -> None:
    if job.temp_script:
        try:
            os.remove(job.temp_script)
        except OSError:
            pass
        job.temp_script = None


def start(command: str, cwd: str, env: dict, temp_script: Optional[str] = None) -> str:
    """Launch *command* in the background and return its job id.

    The job belongs to the ambient identity for its whole life: only calls made
    under the same identity can read or kill it.
    """
    owner = _owner_key()
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=not _IS_WIN,
    )
    job = _Job(f"bash_{uuid.uuid4().hex[:8]}", command, process, temp_script, owner)
    reader = threading.Thread(target=_drain, args=(job, process.stdout), daemon=True)
    job.readers.append(reader)
    reader.start()

    with _lock:
        _evict_finished(owner)
        _jobs[job.id] = job
    return job.id


def read(job_id: str) -> Optional[dict]:
    """Output printed since the last read, plus current status.

    Returns None when *job_id* is unknown, or when it belongs to another
    conversation - a job is never someone else's to poll.
    """
    owner = _owner_key()
    with _lock:
        job = _jobs.get(job_id)
    if job is None or job.owner != owner:
        return None

    output, dropped = job.take_new_output()
    running = job.running
    if not running:
        # Give the reader a moment to flush whatever was buffered at exit.
        for reader in job.readers:
            reader.join(timeout=1)
        tail, more_dropped = job.take_new_output(final=True)
        output += tail
        dropped += more_dropped
        _cleanup(job)

    return {
        "id": job.id,
        "command": job.command,
        "running": running,
        "exit_code": None if running else job.process.returncode,
        "output": output,
        "dropped_bytes": dropped,
        "elapsed": round(time.time() - job.started_at, 1),
    }


def kill(job_id: str) -> Optional[bool]:
    """Terminate a background job. Returns None when *job_id* is unknown or
    belongs to another conversation."""
    owner = _owner_key()
    with _lock:
        job = _jobs.get(job_id)
    if job is None or job.owner != owner:
        return None
    if job.running:
        _kill_process(job.process)
        job.process.wait()
    _cleanup(job)
    return True


def list_jobs() -> List[dict]:
    """The ambient conversation's jobs.

    This backs the model-facing "no such id, currently tracked: ..." message, so
    it must not name jobs the caller cannot poll.
    """
    owner = _owner_key()
    with _lock:
        jobs = [j for j in _jobs.values() if j.owner == owner]
    return [
        {
            "id": j.id,
            "command": j.command,
            "running": j.running,
            "elapsed": round(time.time() - j.started_at, 1),
        }
        for j in jobs
    ]


def _kill_process(process: subprocess.Popen) -> None:
    """Kill the whole process group - a shell command is usually a tree."""
    if _IS_WIN:
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0 and process.poll() is None:
                process.kill()
        except (OSError, subprocess.SubprocessError):
            if process.poll() is None:
                process.kill()
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            if process.poll() is None:
                process.kill()


def reset() -> None:
    """Kill everything and clear the registry (tests)."""
    with _lock:
        jobs = list(_jobs.values())
        _jobs.clear()
    for job in jobs:
        if job.running:
            _kill_process(job.process)
        _cleanup(job)
