"""Size-capped HTTP downloads for media that channels receive or send.

Bodies are streamed and counted chunk by chunk, so a huge or endless response
is cut off at ``max_bytes`` instead of being buffered into memory first.
``max_seconds`` optionally caps the whole transfer, since the socket timeout
alone never fires on a server that keeps trickling bytes.
Every failure raises; callers decide how to degrade.
"""

import os
import tempfile
import time
from typing import NamedTuple

import requests

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024

_CHUNK_SIZE = 64 * 1024
_DEFAULT_TIMEOUT = (5, 60)


class MediaTooLargeError(ValueError):
    pass


class DownloadResult(NamedTuple):
    size: int
    content_type: str


def download_to_file(url, path, max_bytes=MAX_FILE_BYTES, timeout=_DEFAULT_TIMEOUT, max_seconds=None,
                     **kwargs) -> DownloadResult:
    """Stream ``url`` into ``path``.

    The body goes to a temp file next to ``path`` and is moved into place only
    once it arrived completely within ``max_bytes``, so a failed or oversized
    download never leaves a partial file behind or clobbers an existing one.
    Extra ``kwargs`` (headers, params, ...) are passed to ``requests.get``.
    """
    temp_path = None
    deadline = _deadline(max_seconds)
    response = _open(url, max_bytes, timeout, kwargs)
    try:
        size = 0
        with tempfile.NamedTemporaryFile(
            dir=os.path.dirname(path) or ".", prefix=".download_", delete=False
        ) as out:
            temp_path = out.name
            for chunk in _read_chunks(response, max_bytes, deadline):
                out.write(chunk)
                size += len(chunk)
        os.replace(temp_path, path)
        temp_path = None
        return DownloadResult(size, response.headers.get("Content-Type", ""))
    finally:
        response.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def download_bytes(url, max_bytes=MAX_FILE_BYTES, timeout=_DEFAULT_TIMEOUT, max_seconds=None, **kwargs) -> bytes:
    """Return the body of ``url``, refusing anything larger than ``max_bytes``."""
    deadline = _deadline(max_seconds)
    response = _open(url, max_bytes, timeout, kwargs)
    try:
        return b"".join(_read_chunks(response, max_bytes, deadline))
    finally:
        response.close()


def _open(url, max_bytes, timeout, kwargs):
    response = requests.get(url, stream=True, timeout=timeout, **kwargs)
    try:
        response.raise_for_status()
        try:
            declared = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > max_bytes:
            raise MediaTooLargeError(f"media too large: {declared} bytes, limit {max_bytes}")
    except Exception:
        response.close()
        raise
    return response


def _deadline(max_seconds):
    return time.monotonic() + max_seconds if max_seconds else None


def _read_chunks(response, max_bytes, deadline=None):
    size = 0
    for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
        if deadline is not None and time.monotonic() > deadline:
            raise requests.exceptions.Timeout("media download took too long")
        if not chunk:
            continue
        size += len(chunk)
        if size > max_bytes:
            raise MediaTooLargeError(f"media too large: over limit {max_bytes} bytes")
        yield chunk
