"""Replace a file's contents without ever leaving it half-written.

Writing straight into a file truncates it before the new bytes exist, so a
crash, a kill or a full disk in between leaves a partial document that most
stores here cannot parse back. These helpers write a sibling first and rename
it over the target, so readers see either the old file or the new one.

The sibling is dot-prefixed (workspace watchers skip it) and unique per call,
so overlapping writers never rename each other's partial file.

Some targets can be written but not renamed over: a single-file Docker bind
mount (EBUSY / EXDEV), a file another handle holds open on Windows
(PermissionError), or a writable file in a directory that is not. Those fall
back to writing in place; the content is fully serialised by then, so the
fallback cannot leave a half-encoded document behind.
"""

import errno
import io
import json
import os
import stat
import uuid

_IN_PLACE_ERRNOS = (errno.EBUSY, errno.EXDEV, errno.EACCES, errno.EPERM)


def write_text_atomic(path, text: str, encoding: str = "utf-8", newline=None) -> None:
    """``newline`` is passed to ``open``; ``''`` writes ``text`` verbatim."""
    _replace(path, lambda f: f.write(text), encoding, newline)


def write_json_atomic(path, data, indent: int = 4, ensure_ascii: bool = False) -> None:
    _replace(path, lambda f: json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii))


def write_bytes_atomic(path, data: bytes) -> None:
    """Byte-level sibling of ``write_text_atomic`` (pickle, media, ...)."""
    _replace(path, lambda f: f.write(data), binary=True)


def _replace(path, write, encoding: str = "utf-8", newline=None, binary: bool = False) -> None:
    # Resolve symlinks so the link keeps pointing at the updated file instead
    # of being swapped for a regular one.
    target = os.path.realpath(os.fspath(path))
    directory, name = os.path.split(target)
    tmp_path = os.path.join(directory, f".{name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        # Stage with the target's own mode, so a private file is never readable
        # mid-write while a new file keeps the umask default.
        try:
            target_stat = os.stat(target)
        except OSError:
            mode = 0o666
        else:
            if not stat.S_ISREG(target_stat.st_mode):
                raise OSError(errno.EINVAL, "target is not a regular file", target)
            mode = stat.S_IMODE(target_stat.st_mode)
        # encoding/newline are text-mode options; in binary mode both are None.
        f = open(
            tmp_path, "wb" if binary else "w",
            encoding=None if binary else encoding,
            newline=None if binary else newline,
            opener=lambda name, flags: os.open(name, flags | os.O_EXCL, mode),
        )
    except OSError as e:
        if not _can_write_in_place(e, target):
            raise
        if binary:
            buffer = io.BytesIO()
            write(buffer)
            _write_bytes_in_place(target, buffer.getvalue(), e)
        else:
            buffer = io.StringIO()
            write(buffer)
            _write_in_place(target, buffer.getvalue(), encoding, e, newline)
        return
    try:
        with f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        _copy_mode(target, tmp_path)
        try:
            os.replace(tmp_path, target)
        except OSError as e:
            if not _can_write_in_place(e, target):
                raise
            # Copy what is already on disk, byte-exact in binary mode,
            # line endings included in text mode.
            if binary:
                with open(tmp_path, "rb") as src:
                    data = src.read()
                _write_bytes_in_place(target, data, e)
            else:
                with open(tmp_path, "r", encoding=encoding, newline="") as src:
                    text = src.read()
                _write_in_place(target, text, encoding, e, "")
            _remove_quietly(tmp_path)
    except BaseException:
        _remove_quietly(tmp_path)
        raise


def _can_write_in_place(error: OSError, target: str) -> bool:
    if not os.path.isfile(target):
        return False
    return isinstance(error, PermissionError) or error.errno in _IN_PLACE_ERRNOS


def _write_in_place(target: str, text: str, encoding: str, cause: OSError, newline=None) -> None:
    from common.log import logger

    # Encode and translate newlines before opening the existing file with
    # truncation. StringIO alone cannot catch an invalid character/encoding.
    buffer = io.BytesIO()
    with io.TextIOWrapper(buffer, encoding=encoding, newline=newline) as staged:
        staged.write(text)
        staged.flush()
        encoded = buffer.getvalue()
    logger.warning(f"[AtomicWrite] Cannot replace {target} ({cause}), writing in place")
    with open(target, "wb") as f:
        f.write(encoded)
        f.flush()
        os.fsync(f.fileno())


def _write_bytes_in_place(target: str, data: bytes, cause: OSError) -> None:
    from common.log import logger

    logger.warning(f"[AtomicWrite] Cannot replace {target} ({cause}), writing in place")
    with open(target, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _copy_mode(src: str, dst: str) -> None:
    """Keep the target's permissions, e.g. 0600 on a credentials file."""
    try:
        os.chmod(dst, stat.S_IMODE(os.stat(src).st_mode))
    except OSError:
        pass
