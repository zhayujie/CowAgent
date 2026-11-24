"""
What keeps code run by the python tool inside the bounds of its session.

The code runs in the agent's own interpreter, so this is a guard rather than a
sandbox: an audit hook refuses starting programs, changing state the whole
process shares, and writes the session's permission mode does not allow, in
the run's thread and in any thread it starts. A C extension can still do as it
likes.
"""

import os
import sys
import threading
from typing import Callable, Dict, Optional

# Audit events refused outright, with what to tell the code.
_REFUSED = {
    "subprocess.Popen": "starting a program",
    "os.system": "starting a program",
    "os.exec": "starting a program",
    "os.posix_spawn": "starting a program",
    "os.spawn": "starting a program",
    "os.fork": "starting a process",
    "os.forkpty": "starting a process",
    "os.startfile": "opening a file with another program",
    "os.kill": "sending signals",
    "os.killpg": "sending signals",
    "os.chdir": "changing the working directory, which the whole app shares (use absolute paths)",
    "os.putenv": "changing environment variables, which the whole app shares",
    "os.unsetenv": "changing environment variables, which the whole app shares",
    "sys.addaudithook": "adding audit hooks",
    "ctypes.dlopen": "loading native libraries",
    "ctypes.dlsym": "calling native code",
}

# Audit events that write, with the positions of the paths they write.
_WRITES = {
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.rename": (0, 1),
    "os.replace": (0, 1),
    "os.truncate": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.utime": (0,),
    "os.link": (1,),
    "os.symlink": (1,),
    "os.setxattr": (0,),
    "os.removexattr": (0,),
    "shutil.rmtree": (0,),
    "shutil.copyfile": (1,),
    "shutil.copytree": (1,),
    "shutil.move": (0, 1),
    "shutil.chown": (0,),
    "sqlite3.connect": (0,),
}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_IN_MEMORY_DB = (":memory:", "", "file::memory:")


class Output:
    """The end of what a run printed: an endless loop of prints must not eat the app's memory."""

    LIMIT = 256 * 1024

    def __init__(self):
        self._parts = []
        self._size = 0
        self.dropped = 0
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            self._parts.append(text)
            self._size += len(text)
            while self._size > self.LIMIT and len(self._parts) > 1:
                gone = self._parts.pop(0)
                self._size -= len(gone)
                self.dropped += len(gone)
            if self._size > self.LIMIT:
                cut = self._size - self.LIMIT
                self._parts[0] = self._parts[0][cut:]
                self._size -= cut
                self.dropped += cut

    def text(self) -> str:
        with self._lock:
            return "".join(self._parts)


class Run:
    """One call of the tool: how its writes are checked, where its prints go, which threads are its own."""

    def __init__(self, check_write: Callable[[str], Optional[str]]):
        self.check_write = check_write
        self.output = Output()
        self.threads = set()


_runs: Dict[int, Run] = {}
_local = threading.local()
_installed = False
_install_lock = threading.Lock()


def enter(run: Run) -> None:
    ident = threading.get_ident()
    _runs[ident] = run
    run.threads.add(ident)


def leave(run: Run) -> None:
    ident = threading.get_ident()
    _runs.pop(ident, None)
    run.threads.discard(ident)


def interrupt(run: Run, exc_type: type) -> None:
    """Raise ``exc_type`` in every thread of the run, at its next Python instruction."""
    import ctypes

    for ident in list(run.threads):
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), ctypes.py_object(exc_type))


def _path(value) -> Optional[str]:
    if isinstance(value, int) or value is None:
        return None
    try:
        return os.path.abspath(os.fsdecode(os.fspath(value)))
    except (TypeError, ValueError):
        return None


def _written_paths(event: str, args: tuple) -> list:
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writes = any(c in mode for c in "wax+") if isinstance(mode, str) else bool(
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        return [args[0]] if writes and args else []
    if event == "sqlite3.connect":
        database = args[0] if args else None
        if isinstance(database, str) and database in _IN_MEMORY_DB:
            return []
    return [args[i] for i in _WRITES.get(event, ()) if i < len(args)]


def _hook(event: str, args: tuple) -> None:
    run = _runs.get(threading.get_ident())
    if run is None or getattr(_local, "busy", False):
        return
    what = _REFUSED.get(event)
    if what:
        raise PermissionError(f"Not possible here: {what}.")
    if event != "open" and event not in _WRITES:
        return
    _local.busy = True
    try:
        for value in _written_paths(event, args):
            path = _path(value)
            reason = path and run.check_write(path)
            if reason:
                raise PermissionError(reason)
    finally:
        _local.busy = False


class _Router:
    """sys.stdout / sys.stderr: a run's prints go to the run, everyone else's where they always went."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        run = _runs.get(threading.get_ident())
        if run is not None:
            run.output.write(str(text))
            return len(text)
        return self._stream.write(text) if self._stream is not None else len(text)

    def flush(self):
        if _runs.get(threading.get_ident()) is None and self._stream is not None:
            self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _guard_exit(original, what: str):
    def guarded(*args, **kwargs):
        if threading.get_ident() in _runs:
            raise PermissionError(f"Not possible here: {what} would close the whole app.")
        return original(*args, **kwargs)
    return guarded


def _start_in_run(original):
    """Threads a run starts belong to it: checked the same way, printing to it, stopped with it."""
    def start(self):
        run = _runs.get(threading.get_ident())
        if run is not None:
            body = self.run

            def run_in_run():
                enter(run)
                try:
                    body()
                finally:
                    leave(run)

            self.run = run_in_run
        return original(self)
    return start


def install() -> None:
    """Idempotent; touches nothing until the first run, so a process that never uses the tool stays as it was."""
    global _installed
    with _install_lock:
        if not _installed:
            sys.addaudithook(_hook)
            threading.Thread.start = _start_in_run(threading.Thread.start)
            os._exit = _guard_exit(os._exit, "os._exit()")
            os.abort = _guard_exit(os.abort, "os.abort()")
            _installed = True
        # Checked every run: whoever replaced the streams since is wrapped in turn.
        if not isinstance(sys.stdout, _Router):
            sys.stdout = _Router(sys.stdout)
        if not isinstance(sys.stderr, _Router):
            sys.stderr = _Router(sys.stderr)
