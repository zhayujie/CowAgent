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


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    _replace(path, lambda f: f.write(text), encoding)


def write_json_atomic(path, data, indent: int = 4, ensure_ascii: bool = False) -> None:
    _replace(path, lambda f: json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii))


def _replace(path, write, encoding: str = "utf-8") -> None:
    # Resolve symlinks so the link keeps pointing at the updated file instead
    # of being swapped for a regular one.
    target = os.path.realpath(os.fspath(path))
    directory, name = os.path.split(target)
    tmp_path = os.path.join(directory, f".{name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        f = open(tmp_path, "w", encoding=encoding)
    except OSError as e:
        if not _can_write_in_place(e, target):
            raise
        buffer = io.StringIO()
        write(buffer)
        _write_in_place(target, buffer.getvalue(), encoding, e)
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
            with open(tmp_path, "r", encoding=encoding) as src:
                text = src.read()
            _write_in_place(target, text, encoding, e)
            _remove_quietly(tmp_path)
    except BaseException:
        _remove_quietly(tmp_path)
        raise


def _can_write_in_place(error: OSError, target: str) -> bool:
    if not os.path.isfile(target):
        return False
    return isinstance(error, PermissionError) or error.errno in _IN_PLACE_ERRNOS


def _write_in_place(target: str, text: str, encoding: str, cause: OSError) -> None:
    from common.log import logger

    logger.warning(f"[AtomicWrite] Cannot replace {target} ({cause}), writing in place")
    with open(target, "w", encoding=encoding) as f:
        f.write(text)
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
