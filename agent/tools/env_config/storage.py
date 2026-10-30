"""Small shared primitives for coordinated credentials edits (no model tools)."""

import hashlib
import os
import stat
import tempfile
import threading
import time
from contextlib import contextmanager

_locks = {}
_locks_guard = threading.Lock()


def _lock_path(path):
    from common.utils import expand_path

    # Keep coordination files separate from the credentials directory's data
    # layout. The target path, not the calling tool, identifies a shared lock.
    identity = os.path.normcase(os.path.realpath(os.fspath(path)))
    digest = hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()
    return os.path.join(expand_path("~/.cow/locks"), "env-" + digest + ".lock")


@contextmanager
def env_file_lock(path, timeout=10):
    """Serialize read/modify/write across threads and cooperating processes.

    The lock stays in place: unlinking a lock file lets two processes lock
    different inodes. Editors outside CowAgent do not participate in this lock.
    """
    path = os.path.abspath(os.fspath(path))
    with _locks_guard:
        lock = _locks.setdefault(path, threading.RLock())
    with lock:
        lock_path = _lock_path(path)
        os.makedirs(os.path.dirname(lock_path), mode=0o700, exist_ok=True)
        if os.path.islink(lock_path):
            raise OSError("Invalid credentials lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("Invalid credentials lock")
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            deadline = time.monotonic() + timeout
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Credentials are busy") from None
                    time.sleep(0.025)
            try:
                yield
            finally:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def write_private_atomic(path, text):
    """Strict atomic replacement: never fall back to truncating credentials.

    common.atomic_write intentionally falls back to in-place writes for bind
    mounts and locked Windows files. Here that condition must fail safely.
    Both the staging file and the replacement have mode 0600 on POSIX.
    """
    data = text.encode("utf-8")
    path = os.fspath(path)
    if os.path.lexists(path) and (os.path.islink(path) or not os.path.isfile(path)):
        raise OSError("Invalid credentials target")
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".env-private-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name != "nt":
            # Persist the directory entry as well as file bytes: the dirty
            # metadata replacement must be durable before the .env swap.
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
